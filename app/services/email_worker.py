"""Bounded retries and PostgreSQL locking; SMTP delivery is at-least-once."""

import asyncio
import hmac
from datetime import timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.models.accounts import Account
from app.models.entities import utcnow
from app.models.notifications import EmailOutbox, EmailSubscription
from app.observability.events import emit
from app.services.accounts import verification_digest
from app.services.mailer import send_case_email


async def deliver_one(db, sender=send_case_email):
    if not get_settings().email_enabled:
        return False
    async with db.begin():
        row = await db.scalar(
            select(EmailOutbox)
            .where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= utcnow())
            .order_by(EmailOutbox.created_at, EmailOutbox.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        if row.kind == "verify_account":
            account = await db.scalar(
                select(Account).where(Account.id == row.customer_id).with_for_update()
            )
            expires = account.verification_expires if account else None
            if expires and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            valid = bool(
                account
                and not account.email_verified
                and account.email == row.recipient
                and row.verification_code
                and account.verification_hash
                and expires
                and expires > utcnow()
                and hmac.compare_digest(
                    verification_digest(account.id, row.verification_code),
                    account.verification_hash,
                )
            )
        else:
            subscription = await db.scalar(
                select(EmailSubscription)
                .where(EmailSubscription.case_id == row.case_id)
                .with_for_update()
            )
            valid = bool(
                subscription
                and subscription.enabled
                and subscription.recipient == row.recipient
                and subscription.customer_id == row.customer_id
                and subscription.delivery_mode == row.delivery_mode
            )
        if not valid or row.delivery_mode != get_settings().email_delivery_mode:
            row.status = "skipped"
        else:
            row.attempts += 1
            try:
                await asyncio.to_thread(sender, row)
                row.status, row.sent_at = "sent", utcnow()
                row.last_error_type = None
                row.verification_code = None
            except Exception as exc:
                row.last_error_type = type(exc).__name__[:100]
                row.status = "failed" if row.attempts >= 5 else "pending"
                row.next_attempt_at = utcnow() + timedelta(seconds=min(30 * 2**row.attempts, 3600))
        emit(
            "email_delivery_attempt",
            outcome=row.status,
            attempts=row.attempts,
            error_type=row.last_error_type,
        )
    return True


async def dispatch_emails(stop, sessions):
    """API-managed dispatcher; bounded batches and graceful shutdown."""
    while not stop.is_set():
        try:
            for _ in range(10):
                if stop.is_set():
                    return
                async with sessions() as db:
                    if not await deliver_one(db):
                        break
        except Exception as exc:
            emit("email_dispatcher_error", error_type=type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
