import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.api.v1.routes import router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.observability.events import configure_logging
from app.observability.middleware import RequestTelemetryMiddleware
from app.services.email_worker import dispatch_emails


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    async with AsyncPostgresSaver.from_conn_string(get_settings().checkpoint_database_url) as saver:
        await saver.setup()  # Idempotent checkpoint schema initialization
        app.state.checkpointer = saver
        stop = asyncio.Event()
        task = (
            asyncio.create_task(dispatch_emails(stop, SessionLocal))
            if get_settings().email_enabled and get_settings().email_worker_in_api
            else None
        )
        try:
            yield
        finally:
            stop.set()
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=15)
                except TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="SupportFlow AI", lifespan=lifespan)
app.add_middleware(RequestTelemetryMiddleware)
app.include_router(router)
