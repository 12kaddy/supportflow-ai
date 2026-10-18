# Email notifications

Verified OIDC customers automatically receive approval, rejection, and completed-
simulation email updates for new cases when SMTP notifications are enabled.
Existing explicit case opt-outs are preserved. The verified recipient is taken
from signed account claims, not a user-entered tool argument. Re-reporting an active
owned case can initialize a missing subscription; merely viewing it does not.
Messages contain a case reference and status, not the report, evidence, internal
reviewer notes, or exact financial details. They explicitly distinguish approval
from execution and simulated refunds from real payments.

## Free local testing

Mailpit captures email without delivering it to real inboxes:

```powershell
docker compose -f docker-compose.yml -f docker-compose.email.yml up -d mailpit
alembic upgrade head
```

Configure `.env` and restart FastAPI:

```dotenv
EMAIL_ENABLED=true
EMAIL_DELIVERY_MODE=local
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
EMAIL_FROM=supportflow@localhost
```

For a containerized API/worker on the same Compose network, use `SMTP_HOST=mailpit`.
The mail UI is at `http://localhost:8025`. Mailpit's ports bind only to localhost.
The provided container has no external SMTP relay configured.

For local capture only, use **Customer chat → Email preferences (optional)** to
enter an owned case ID and test address, then enable updates. Real SMTP does not
require this manual enrollment for new verified-account cases. Existing events
are not backfilled. Customers can opt out using the same preferences. Endpoints are:

```text
GET /v1/cases/{case_id}/email-subscription
PUT /v1/cases/{case_id}/email-subscription
```

Local subscription body:

```json
{"enabled":true,"email":"customer@example.test"}
```

The API starts a dispatcher automatically when `EMAIL_ENABLED=true` and
`EMAIL_WORKER_IN_API=true` (the default). Restart the API after configuration
changes. A separate worker terminal is no longer required for normal local use.
For a dedicated worker deployment, set `EMAIL_WORKER_IN_API=false` and run:

```powershell
python -m scripts.email_worker --watch
```

Without `--watch` it processes up to 100 currently due messages once and exits.
The API dispatcher does not send SMTP inside a customer/reviewer request. Worker/API settings
must agree. Email is disabled by default and workers do nothing while disabled.

## Deliver to a real inbox

Real delivery needs an SMTP server/account. Open-source software does not provide
inbox delivery, sender reputation, or a free provider account automatically.
Use OIDC authentication, verify the user's email in the identity provider, and set:

```dotenv
EMAIL_ENABLED=true
EMAIL_DELIVERY_MODE=smtp
SMTP_HOST=your-smtp-host
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=your-account
SMTP_PASSWORD=your-secret
EMAIL_FROM=your-authorized-sender@example.com
```

SMTP mode only accepts the signed OIDC token's `email` claim with
`email_verified=true`. A customer cannot substitute another recipient, and demo
authentication cannot enroll external recipients. Include the `email` scope at
login (the login helper requests it). SMTP enrollment happens automatically during
case creation for that verified account. In optional preferences, leave the
test-address field blank; the verified account address is used. STARTTLS is mandatory for external
transport; implicit TLS on port 465 is not implemented.

## Delivery guarantees and privacy

Each review/execution queues at most one email per case/event in the same database
transaction. Rollback removes both the state change and its queued notification.
PostgreSQL workers use row locks with `SKIP LOCKED`, so concurrent workers do not
normally send the same queued event. Failed deliveries retry up to five times with
exponential delay, then become `failed`. Stored/logged errors contain only exception
types. SMTP acceptance is recorded as `sent`, not proof the inbox received or read it.

Turn off updates with `{"enabled":false}`. Workers recheck opt-in and address before
delivery and skip obsolete queued messages. Changing between local and real SMTP
modes also skips old-mode messages; enroll again for the new mode. An already
accepted/in-progress SMTP send cannot be recalled.

SMTP is not exactly-once: a crash after the server accepts mail but before the
database commit can cause a duplicate. Stable Message-ID values help identify
retries but do not guarantee recipient deduplication. Sent/failed queue rows remain
in PostgreSQL; retention, bounce handling, unsubscribe links, and provider-specific
delivery webhooks are not implemented. The authenticated preference endpoint is
the current unsubscribe mechanism. Keep the existing API ownership limitations
in mind if using demo authentication.

Reference: [Mailpit local SMTP testing](https://mailpit.axllent.org/docs/usage/sending-messages/).
