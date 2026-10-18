"""Create the first local admin interactively; subsequent admins use the API."""

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.accounts import Account
from app.schemas.accounts import RegisterRequest
from app.services.accounts import create_account


async def bootstrap(body):
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(text("SELECT pg_advisory_xact_lock(831246015)"))
            if await db.scalar(select(Account.id).where(Account.role == "admin").limit(1)):
                raise RuntimeError(
                    "An admin already exists. Use an authenticated admin to create another."
                )
            await create_account(db, body, "admin")
    print("First admin created. Log in through the application.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Administrator")
    args = parser.parse_args()
    password = getpass("Admin password (at least 12 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    asyncio.run(bootstrap(RegisterRequest(email=args.email, name=args.name, password=password)))
