from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.agents.graph import build_graph
from app.api.v1.accounts import router as accounts_router
from app.api.v1.email_notifications import router as email_router
from app.api.v1.resolutions import router as resolution_router
from app.api.v1.voice import router as voice_router
from app.core.config import get_settings
from app.core.customer_contact import customer_email
from app.core.security import identity
from app.db.session import SessionLocal
from app.observability.events import emit
from app.repositories.orders import get_order, request_refund
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.disputes import DisputeRequest
from app.services.chat_runtime import ChatProviderError, invoke_chat
from app.services.disputes import get_dispute, open_dispute, serialize_case

router = APIRouter(prefix="/v1")
router.include_router(resolution_router, prefix="")
router.include_router(email_router)
router.include_router(accounts_router)
router.include_router(voice_router)


@router.get("/me")
async def current_customer(customer_id: str = Depends(identity)):
    return {"customer_id": customer_id, "auth_mode": get_settings().auth_mode}


@router.post("/cases", status_code=201)
async def create_case(
    body: DisputeRequest,
    customer_id: str = Depends(identity),
    verified_email: str | None = Depends(customer_email),
):
    async with SessionLocal() as db:
        case = await open_dispute(db, body.order_id, customer_id, body.issue, verified_email)
        if case is None:
            raise HTTPException(404, "Order not found")
        return serialize_case(case)


@router.get("/cases/{case_id}")
async def case_details(case_id: str, customer_id: str = Depends(identity)):
    async with SessionLocal() as db:
        case = await get_dispute(db, case_id, customer_id)
        if case is None:
            raise HTTPException(404, "Case not found")
        return serialize_case(case)


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/orders/{order_id}")
async def order_details(order_id: str, customer_id: str = Depends(identity)):
    async with SessionLocal() as db:
        order = await get_order(db, order_id, customer_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        return {
            "id": order.id,
            "status": order.status,
            "amount_cents": order.amount_cents,
            "days_since_delivery": order.days_since_delivery,
        }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    customer_id: str = Depends(identity),
    verified_email: str | None = Depends(customer_email),
):
    # Namespacing prevents cross-customer thread collisions.
    thread = f"{customer_id}:{body.thread_id}"
    try:
        graph = build_graph(customer_id, request.app.state.checkpointer, verified_email)
    except Exception as exc:
        emit("chat_initialization_failed", error_type=type(exc).__name__)
        raise HTTPException(503, "Chat is unavailable. Check server configuration.") from None
    try:
        result = await invoke_chat(graph, body.message, thread)
    except ChatProviderError as exc:
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        raise HTTPException(exc.status, exc.detail, headers=headers) from None
    except Exception:
        raise HTTPException(
            500, "Chat failed. Use the X-Request-ID response header when contacting support."
        ) from None
    return ChatResponse(answer=str(result["messages"][-1].content), thread_id=body.thread_id)


class RefundRequest(BaseModel):
    order_id: str
    confirm: bool = False


@router.post("/refunds")
async def refund(body: RefundRequest, customer_id: str = Depends(identity)):
    if not body.confirm:
        raise HTTPException(400, "Explicit confirmation required: confirm=true")
    async with SessionLocal() as db:
        result = await request_refund(db, body.order_id, customer_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
