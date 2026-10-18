import hmac
from datetime import timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.local_tokens import local_claims
from app.db.session import SessionLocal
from app.models.accounts import Account
from app.models.entities import utcnow
from app.schemas.accounts import LoginRequest, RegisterRequest, VerifyRequest
from app.services.accounts import (
    authenticate,
    create_account,
    login,
    profile,
    queue_verification,
    verification_digest,
)

router = APIRouter(prefix="/auth", tags=["accounts"])


def local_mode():
    if get_settings().auth_mode != "local":
        raise HTTPException(404, "Local account authentication is not enabled")


def admin(authorization: str = Header(default="")):
    local_mode()
    return local_claims(authorization, "admin")["sub"]


@router.get("/config")
async def config():
    return {"mode": get_settings().auth_mode}


async def register_account(body, role):
    try:
        async with SessionLocal() as db:
            async with db.begin():
                account = await create_account(db, body, role)
            return profile(account)
    except IntegrityError:
        raise HTTPException(409, "An account already uses this email") from None


@router.post("/register", status_code=201, dependencies=[Depends(local_mode)])
async def register(body: RegisterRequest):
    return await register_account(body, "customer")


@router.post("/login", dependencies=[Depends(local_mode)])
async def sign_in(body: LoginRequest):
    async with SessionLocal() as db:
        result = await login(db, body)
        await db.commit()
        return result


@router.post("/admins", status_code=201)
async def create_admin(body: RegisterRequest, actor=Depends(admin)):
    return await register_account(body, "admin")


@router.post("/users", status_code=201)
async def create_customer(body: RegisterRequest, actor=Depends(admin)):
    return await register_account(body, "customer")


@router.get("/users")
async def list_users(actor=Depends(admin)):
    async with SessionLocal() as db:
        users = await db.scalars(select(Account).order_by(Account.created_at.desc()).limit(100))
        return {"items": [profile(user) for user in users]}


@router.post("/verify-email", dependencies=[Depends(local_mode)])
async def verify_email(body: VerifyRequest):
    success = False
    async with SessionLocal() as db:
        async with db.begin():
            account = await db.scalar(
                select(Account).where(Account.email == body.email.strip().lower()).with_for_update()
            )
            if account and not account.email_verified and account.verification_expires:
                expires = account.verification_expires
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires > utcnow() and account.verification_attempts < 5:
                    account.verification_attempts += 1
                    if account.verification_hash and hmac.compare_digest(
                        verification_digest(account.id, body.code), account.verification_hash
                    ):
                        account.email_verified = True
                        account.verification_hash = None
                        success = True
    if not success:
        raise HTTPException(400, "Verification code is invalid or expired. Request a new code.")
    return {"verified": True, "message": "Email verified. Log in to refresh your account session."}


@router.post("/resend-verification", dependencies=[Depends(local_mode)])
async def resend(body: LoginRequest):
    if not get_settings().email_enabled:
        raise HTTPException(503, "Email service is disabled")
    async with SessionLocal() as db:
        async with db.begin():
            account = await authenticate(db, body.email, body.password)
            account = await db.scalar(
                select(Account).where(Account.id == account.id).with_for_update()
            )
            if account.email_verified:
                return {"message": "Email is already verified"}
            sent = account.verification_sent_at
            if (
                sent
                and (
                    utcnow() - (sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc))
                ).total_seconds()
                < 60
            ):
                raise HTTPException(429, "Wait one minute before requesting another code")
            await queue_verification(db, account)
    return {"message": "Verification email queued"}
