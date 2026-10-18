# SupportFlow AI

A customer-support resolution demo with AI chat, policy retrieval, human review,
simulated refunds, and automatic case-status emails.

## Main workflow

Customer registration and email verification → chat reports a delivery issue →
the backend gathers stored evidence and proposes a policy decision → an admin
reviews the case → approved actions execute as simulations → the customer receives
a status email when notifications are enabled.

The LLM can inspect orders, search policies, and open or read customer-owned cases.
It cannot approve or execute refunds. Backend policy checks, transactions, order
locks, and unique constraints protect those operations.

## Local setup

Requires Python 3.11 or 3.12, Docker Compose, and a Groq API key for chat.
Run commands from the project root.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
# On a new checkout, copy .env.example to .env and configure GROQ_API_KEY.
docker compose up -d db
alembic upgrade head
python -m scripts.ingest
python -m scripts.create_admin --email YOUR_ADMIN_EMAIL --name "Administrator"
```

Set `AUTH_MODE=local` in `.env`. The admin setup command prompts privately for
a password. It only bootstraps the first admin; additional accounts are created
by an authenticated admin.

Start the API and frontend in separate terminals:

```powershell
uvicorn app.main:app --reload
streamlit run frontend/streamlit_app.py
```

Open [the application](http://localhost:8501) or [API documentation](http://localhost:8000/docs).
Customers register and log in using the same account screen as admins.
Admins receive the reviewer dashboard and account-management workspace.

New accounts do not inherit existing orders. For fictional demo data, find the
customer ID in account management or `GET /v1/me`, then seed owned orders:

```powershell
python -m scripts.seed --customer-id CUSTOMER_UUID --order-prefix USER1
```

Report `USER1-1001` as delivered but not received. Chat reuses an active case;
the lower-level `POST /v1/cases` endpoint creates a separate case per request.

## Email

Set `EMAIL_ENABLED=true`. For free local capture, run:

```powershell
docker compose -f docker-compose.yml -f docker-compose.email.yml up -d mailpit
```

Mailpit's inbox is [localhost:8025](http://localhost:8025). SMTP mode uses your
configured provider and verified account address. New verified-account cases
automatically enable status emails; explicit opt-outs are preserved. The API
runs the dispatcher by default, so a separate worker terminal is optional.

See [email setup and delivery guarantees](docs/email-notifications.md).

## Documentation

| Topic | Guide |
| --- | --- |
| Registration, login, admin setup, email verification | [Local accounts](docs/local-accounts.md) |
| Case decisions, execution, audit and historical suggestions | [Resolution workflow](docs/workflows.md) |
| Hybrid search, policy versions and citations | [Policy retrieval](docs/retrieval.md) |
| Policy, model and retrieval benchmarks | [Evaluation](docs/evaluation.md) |
| Request IDs, telemetry and provider errors | [Operations](docs/operations.md) |
| Optional external identity provider | [Keycloak/OIDC](docs/authentication.md) |
| Microphone, Indian-language speech, interruption and WER | [Voice channel](docs/voice.md) |
| Read-only tools for Inspector and desktop MCP clients | [MCP server](docs/mcp.md) |
| Local Phoenix traces and a reproducible debugging replay | [Tracing](docs/tracing.md) |
| Input PII/injection checks and grounded case responses | [Guardrails](docs/guardrails.md) |
| Groq, Ollama/vLLM configuration and fair benchmarks | [Model backends](docs/model-backends.md) |
| Recorded model results and measurement limitations | [Model comparison](docs/model-comparison.md) |
| Architecture and trade-offs | [Decisions](DECISIONS.md) |

Local accounts are the main interface. `AUTH_MODE=oidc` retains the optional
Keycloak integration; `AUTH_MODE=demo` retains the original header-based test mode.
These are distinct identity sources; switching modes does not migrate accounts or
reassign orders. See the relevant guide before switching.

## Verification

```powershell
pytest -q
pytest --postgres -q
ruff check app tests scripts frontend alembic
ruff format --check app tests scripts frontend alembic
python -m scripts.evaluate
python -m scripts.evaluate_retrieval
```

PostgreSQL tests use isolated temporary schemas. Set
`SUPPORTFLOW_TEST_DATABASE_URL` to use a dedicated PostgreSQL test database.
Live model evaluation is opt-in and may consume provider quota:

```powershell
python -m scripts.evaluate --mode agent --live
```

CI runs offline checks and benchmarks plus a separate PostgreSQL service job.

## Project structure

- `app/api/v1`: HTTP endpoints and authentication boundaries.
- `app/core`: settings, token verification and identity dependencies.
- `app/services`: account, case, policy and email workflows.
- `app/repositories`, `app/models`, `app/db`: queries and persistence.
- `app/agents`, `app/tools`: agent prompt, orchestration and customer tools.
- `app/rag`: approved policy corpus, keyword/vector search and rank fusion.
- `app/evaluation`: versioned datasets, execution and scoring.
- `app/observability`: content-free operational events and callbacks.
- `frontend`: account screens, workspace routing, chat and reviewer UI.
- `scripts`: setup, seeding, workers and evaluation commands.
- `alembic`: database migration history.
- `docs`: feature-specific setup and reference material.

Keep `.env`, `.local`, signing keys and token files private. Applied migrations,
conversation checkpoints, audit history and evaluation reports are persistent
project state, not disposable cleanup targets.

## Scope

Orders and carrier evidence are fictional; refunds are simulated and never move
money. Source citations do not prove semantic entailment. Evaluation datasets are
small regression benchmarks. Production deployment still needs deployment-level
controls, retention, backups and real external integrations.
