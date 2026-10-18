# Database-backed accounts

Use this mode for the simpler portfolio workflow: registration and login forms,
PostgreSQL accounts, backend-enforced customer/admin roles, and no copied tokens.
Keycloak remains available as an alternative; it is not required in local mode.

## Setup

```powershell
pip install -e '.[dev]'
alembic upgrade head
python -m scripts.create_admin --email YOUR_ADMIN_EMAIL --name "Administrator"
```

The setup command asks for a password without displaying it. It creates only the
first admin and refuses once an admin exists. Passwords require at least 12
characters and are stored only as Argon2 hashes. There is no anonymous create-admin
endpoint. Later admins/customers can be created through **Manage accounts** by an
authenticated admin.

Set `AUTH_MODE=local` in `.env`, then restart FastAPI and Streamlit. Open the
Streamlit app. Customers can register and both roles use the same login form.
Admins see the reviewer dashboard and account management; customers see chat.
No role selection in the public registration form can grant admin access; the
backend fixes the registration role to `customer` and rejects extra role fields.

## Email verification

When `EMAIL_ENABLED=true`, registration automatically queues a six-digit email
verification code through the existing SMTP/Mailpit configuration. Choose
**Verify email**, enter the code within 15 minutes, then log in. Verification codes
are one-use, with five guesses per code; resend requires the account password and
a one-minute cooldown. Codes are HMAC-protected on account records. Pending mail
holds the code until delivery; the worker clears that field after sending.

Verified customers' new cases automatically enroll for case-status emails in SMTP
mode. Customers without verified email can still use chat but do not receive real
notification emails. Local Mailpit verification codes appear in its local inbox.
The API-managed dispatcher delivers account and case emails automatically.

## APIs

| Method | Endpoint | Access |
| --- | --- | --- |
| POST | `/v1/auth/register` | Public; customer accounts only |
| POST | `/v1/auth/login` | Email and password, both roles |
| POST | `/v1/auth/verify-email` | Email and verification code |
| POST | `/v1/auth/resend-verification` | Account credentials |
| POST | `/v1/auth/admins` | Signed-in admin only |
| POST | `/v1/auth/users` | Signed-in admin; creates a customer |
| GET | `/v1/auth/users` | Signed-in admin; latest 100 account profiles |

Passwords, password hashes, and verification secrets are never returned by account
listing APIs. Login temporarily locks an account for five minutes after five wrong
password attempts. Public deployment also needs HTTPS and deployment-level request
limits. Self-service password reset and account deletion are not implemented.

## Session and migration behavior

The UI keeps a 30-minute bearer session in Streamlit session memory and clears
conversation history on logout or identity change. API permissions are verified
independently of the selected frontend page. Local tokens and OIDC tokens are not
interchangeable. Signing uses `LOCAL_AUTH_SECRET` (32+ characters) or an automatically
generated ignored `.local/auth-signing.key`. Keep the key private and stable; share
the same configured secret across API/worker containers or hosts. Rotating it
invalidates local sessions and pending verification codes. Tokens are stateless
until expiry; immediate per-session revocation is not implemented.

This does not copy Keycloak passwords, migrate identities, or reassign old demo
orders. New accounts have stable UUID customer IDs. Use their profile ID to seed
owned demonstration orders if needed:

```powershell
python -m scripts.seed --customer-id CUSTOMER_UUID --order-prefix USER1
```

For a frontend running separately, set `SUPPORTFLOW_UI_AUTH_MODE=local` if its
local configuration differs from the API. The normal local setup reads `AUTH_MODE`
from the same project configuration automatically.
