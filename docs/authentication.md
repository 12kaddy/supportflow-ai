# Local open-source identity with Keycloak

This setup replaces caller-supplied identity in **OIDC mode**. Keycloak is
self-hosted and has no service subscription. Local hardware and hosting still
consume resources. Existing demo authentication stays active until you explicitly
select OIDC mode.

## Start Keycloak

Keycloak's bootstrap password is read from `KEYCLOAK_ADMIN_PASSWORD`. Set a strong
value in your local `.env` or an ignored environment file. This task creates
`.local/keycloak.env` with a generated password for local setup. Start only the
identity service alongside the existing application:

```powershell
docker compose --env-file .local/keycloak.env -f docker-compose.yml -f docker-compose.auth.yml up -d keycloak
```

Open `http://localhost:8080/admin/`. Log in as `admin` using the generated password
from `.local/keycloak.env`. Select realm **supportflow**. The imported realm has a
public `supportflow-ui` client, API audience `supportflow-api`, and `customer` and
`reviewer` roles. It creates no users with shared default passwords.

Create a customer and a reviewer in **Users**, set their passwords in
**Credentials**, and assign the appropriate realm role under **Role mapping**.
Assign only the roles each account needs. The reviewer does not need the customer
role to use the reviewer dashboard. The admin-console account is separate from
application users and does not automatically have support reviewer permissions.

## Configure the API

Install updated dependencies, then set these values in your local `.env`:

```dotenv
AUTH_MODE=oidc
OIDC_ISSUER=http://localhost:8080/realms/supportflow
OIDC_AUDIENCE=supportflow-api
OIDC_JWKS_URL=http://localhost:8080/realms/supportflow/protocol/openid-connect/certs
OIDC_ALLOW_HTTP=true
```

Restart FastAPI. For an API running inside Docker, use
`OIDC_JWKS_URL=http://keycloak:8080/realms/supportflow/protocol/openid-connect/certs`;
keep the externally visible issuer as `http://localhost:8080/realms/supportflow`.
Use the two Compose files together so the API and Keycloak share their network.

In OIDC mode, customer/reviewer demo keys and `X-Customer-ID` are ignored. There
is no fallback to demo authentication on token failure. Bearer tokens must have
a verified RS256 signature, configured issuer/audience, expiry, issued-at time,
subject, and required realm role. The server uses the signed `sub` as the identity;
usernames, editable profile attributes, and request headers cannot override it.
JWKS are fetched from the configured URL, cached briefly, and refreshed for new keys.

Invalid/missing tokens return 401; missing roles return 403; unavailable identity
keys return 503. Subjects must fit the existing 40-character customer ID column.
Access tokens expire after five minutes in the local realm. Token validation does
not introspect every request; immediate logout/revocation enforcement is not included.

## Log in and connect the interface

Run this command, open the printed verification address, and complete the browser
login as an application user:

```powershell
python -m scripts.login --output .local/customer-token.json
```

The helper uses device authorization; it does not collect account passwords.
It stores only an access token and its lifetime in the ignored local output file,
not refresh tokens. Copy its `access_token` value into Streamlit after checking
**Use OIDC access token**. Repeat login with the reviewer account and a separate
output path for the reviewer workspace. Login again when an access token expires.
Token files are credentials; keep them local and do not share them.

To discover the verified customer subject, send the customer bearer token to
`GET /v1/me`. Existing `ORD-*` sample orders still belong to `demo-customer` and
are intentionally not reassigned. Seed new orders for the verified subject:

```powershell
python -m scripts.seed --customer-id YOUR_VERIFIED_SUBJECT --order-prefix OIDC
```

Use `OIDC-1001` for the delivered-but-not-received demo. The seeder refuses to
take over orders belonging to another customer. Use a separate prefix for each
customer. No SQL migration is needed; order ownership, thread namespacing, tools,
and review auditing use the verified identity automatically.

## Development scope

The provided container runs Keycloak's `start-dev` mode, binds to localhost, and
persists its development data in a named volume. For public deployment, configure
HTTPS, a production Keycloak database, backups, account lifecycle, and issuer URLs.
This is working local OIDC infrastructure, not a claim of deployment hardening.
Switching back to `AUTH_MODE=demo` restores the old demo headers; keep OIDC enabled
where identity enforcement is required.

References: [Keycloak Docker setup](https://www.keycloak.org/getting-started/getting-started-docker),
[realm imports](https://www.keycloak.org/server/containers),
[PyJWT signature and claim verification](https://pyjwt.readthedocs.io/en/latest/usage.html).
