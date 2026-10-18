"""Run queued email delivery: python -m scripts.email_worker [--watch]."""

import argparse
import asyncio

from app.db.session import SessionLocal
from app.observability.events import configure_logging
from app.services.email_worker import deliver_one


async def run(watch=False):
    configure_logging()
    while True:
        processed = 0
        for _ in range(100):
            async with SessionLocal() as db:
                if not await deliver_one(db):
                    break
                processed += 1
        print(f"Processed {processed} queued email events", flush=True)
        if not watch:
            return
        await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.watch))
