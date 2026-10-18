import asyncio
import hashlib
import hmac
import secrets
from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from pwdlib import PasswordHash
from sqlalchemy import select

from app.core.config import get_settings
from app.core.local_tokens import issue_token, signing_secret
from app.models.accounts import Account
from app.models.entities import utcnow
from app.models.notifications import EmailOutbox

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("dummy-password-for-timing-only")


def verification_digest(account_id, code):
    return hmac.new(
        signing_secret().encode(), f"{account_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def profile(account):
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "role": account.role,
        "email_verified": account.email_verified,
    }


async def queue_verification(db, account):
    if not get_settings().email_enabled:
        return
    code = f"{secrets.randbelow(1000000):06d}"
    account.verification_hash = verification_digest(account.id, code)
    account.verification_expires = utcnow() + timedelta(minutes=15)
    account.verification_sent_at = utcnow()
    account.verification_attempts = 0
    db.add(
        EmailOutbox(
            id=str(uuid4()),
            case_id=None,
            customer_id=account.id,
            recipient=account.email,
            delivery_mode=get_settings().email_delivery_mode,
            kind="verify_account",
            verification_code=code,
        )
    )


async def create_account(db, body, role="customer"):
    if await db.scalar(select(Account).where(Account.email == body.email)):
        raise HTTPException(409, "An account already uses this email")
    password_hash = await asyncio.to_thread(passwords.hash, body.password)
    account = Account(
        id=str(uuid4()),
        email=body.email,
        name=body.name.strip(),
        password_hash=password_hash,
        role=role,
        email_verified=False,
    )
    db.add(account)
    await db.flush()
    await queue_verification(db, account)
    return account


async def authenticate(db, email, password):
    account = await db.scalar(select(Account).where(Account.email == email).with_for_update())
    if account and account.locked_until:
        locked = account.locked_until
        if (locked if locked.tzinfo else locked.replace(tzinfo=timezone.utc)) > utcnow():
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
    valid = await asyncio.to_thread(
        passwords.verify, password, account.password_hash if account else DUMMY_HASH
    )
    if not account or not valid:
        if account:
            account.failed_logins += 1
            if account.failed_logins >= 5:
                account.locked_until = utcnow() + timedelta(minutes=5)
            await db.commit()
        raise HTTPException(401, "Invalid email or password")
    account.failed_logins = 0
    account.locked_until = None
    return account


async def login(db, body):
    account = await authenticate(db, body.email, body.password)
    return {
        "access_token": issue_token(account),
        "token_type": "bearer",
        "expires_in": 1800,
        "user": profile(account),
    }
