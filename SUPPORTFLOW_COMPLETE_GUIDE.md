# SupportFlow AI — Complete Architecture and Working Guide

Implementation reference: 18 October 2026. This document describes the code in
this repository, including its current limitations. Configuration examples contain
placeholders and development defaults, never the contents of the private `.env`.

## Contents

1. Product purpose and scope
2. Technology and system architecture
3. Code organization and responsibilities
4. Authentication, registration, roles, and sessions
5. Frontend screens and behavior
6. Chat processing, agent tools, and conversation memory
7. Investigation rules and case lifecycle
8. Review, execution, concurrency, and audit
9. Policy retrieval and historical case comparison
10. Database schema and migrations
11. Email notifications and delivery guarantees
12. Complete HTTP API reference
13. Configuration reference
14. Local setup and demonstration walkthrough
15. Deployment and persistence
16. Testing, evaluation, and observability
17. Troubleshooting
18. Implemented boundaries and remaining work
19. Voice channel (new implementation)

## 1. Product purpose and scope

SupportFlow AI is a stateful customer-support resolution application. It combines
natural-language chat with authenticated order access, policy retrieval,
delivery-dispute investigation, human review, simulated refunds, and email updates.

Example: a customer reports that an order is marked delivered but was not received.
The assistant opens or finds the customer's case. The backend snapshots the stored
order and delivery evidence and applies explicit policy rules. A support reviewer
then approves or rejects the proposal. Approval and execution are separate steps.
Execution records a simulated refund; it never transfers real money.

The model chooses customer tools and explains their results. Application code
enforces ownership, eligibility, reviewer permissions, amounts, and transaction
boundaries. This is a modular monolith with one tool-using agent, not a multi-agent
platform or a complete production customer-service suite.

Important terminology:

| Term | Meaning |
| --- | --- |
| Proposal | Deterministic investigation recommendation; no payment authorization |
| Approval | Recorded reviewer authorization for a specified simulated amount |
| Execution | Creation of a simulated refund and resolution of the case |
| Resolved | Simulation completed; does not establish customer satisfaction |
| Local authentication | Application-owned accounts stored in PostgreSQL |
| Local email mode | Mailpit capture; unrelated to the choice of authentication mode |
| Admin | Local account that can review cases and manage accounts |

## 2. Technology and system architecture

| Component | Technology | Responsibility |
| --- | --- | --- |
| Frontend | Streamlit | Account forms, customer chat, reviewer dashboard |
| API | FastAPI / Pydantic | HTTP routes, validation, dependency-based access checks |
| Application | Python 3.11 or 3.12 | Services, policies, integrations, scripts |
| Model integration | LangChain / ChatGroq | Groq chat-model calls and tool integration |
| Default model setting | `openai/gpt-oss-120b` | Hosted inference through Groq |
| Agent orchestration | LangGraph | Model/tool loop and checkpointed conversation state |
| Structured storage | PostgreSQL 16 | Accounts, orders, cases, approvals, audit, email outbox |
| Database access | SQLAlchemy async / asyncpg | Queries and transactions |
| Schema changes | Alembic | Versioned application migrations |
| Conversation storage | LangGraph PostgreSQL checkpointer / psycopg | Durable agent state |
| Policy search | ChromaDB + Sentence Transformers + BM25 | Semantic and lexical retrieval |
| Embedding setting | `all-MiniLM-L6-v2` | Local sentence embeddings |
| Local credentials | pwdlib / Argon2 and PyJWT | Password hashes and signed access tokens |
| Optional external identity | Keycloak / OIDC | RS256 access-token verification |
| Email | SMTP / Mailpit | Real provider delivery or local capture |
| Infrastructure | Docker / Docker Compose | API, database, optional identity and mail services |
| Verification | pytest / Ruff / GitHub Actions | Tests, lint, formatting, regression benchmarks |

```mermaid
flowchart TD
    Customer[Customer] --> UI[Streamlit frontend]
    Admin[Admin / support reviewer] --> UI
    UI --> API[FastAPI /v1]
    API --> Auth[Identity and role dependencies]
    API --> Chat[Chat runtime]
    Chat --> Agent[LangGraph customer agent]
    Agent <--> Groq[Groq model]
    Agent --> Tools[Customer tools]
    Tools --> Cases[Case and order services]
    Tools --> RAG[Hybrid policy retrieval]
    RAG --> Corpus[Versioned Markdown corpus]
    RAG --> Chroma[Persistent Chroma embeddings]
    API --> Review[Reviewer services]
    Cases --> PG[(PostgreSQL)]
    Review --> PG
    Agent <--> Checkpoints[PostgreSQL conversation checkpoints]
    Review --> Outbox[Transactional email outbox]
    Outbox --> Worker[Email dispatcher]
    Worker --> SMTP[SMTP provider or Mailpit]
```

PostgreSQL holds business records and graph checkpoints in distinct tables. Chroma
holds search vectors. Policy Markdown and its manifest remain the approved source
corpus. The SMTP provider handles mail transport; accepting a message does not
prove inbox delivery.

## 3. Code organization and responsibilities

| Location | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI lifecycle, checkpoint setup, email dispatcher, middleware |
| `app/api/v1/routes.py` | Chat, identity, orders, customer cases, health, legacy refunds |
| `app/api/v1/accounts.py` | Local registration, login, verification, account administration |
| `app/api/v1/resolutions.py` | Reviewer queue, details, review, execution, audit, similarity |
| `app/api/v1/email_notifications.py` | Owned-case email preference endpoints |
| `app/core/config.py` | Cached environment-backed settings |
| `app/core/access_tokens.py` | Shared dispatch to local or OIDC token verification |
| `app/core/security.py` | Customer authentication dependency |
| `app/core/reviewer_auth.py` | Reviewer authentication dependency |
| `app/core/local_tokens.py` | Local signing key, token issuance, claim and role checks |
| `app/core/oidc.py` | Issuer/JWKS configuration and external token checks |
| `app/core/customer_contact.py` | Verified account email extraction |
| `app/services/` | Accounts, investigations, review, execution, chat, email, case similarity |
| `app/repositories/` | Ownership queries, ordering, locks, historical candidates, audit writes |
| `app/models/` | SQLAlchemy application entities |
| `app/schemas/` | Request/response models and shared email validation |
| `app/db/` | Declarative base and async session factory |
| `app/agents/graph.py` | System prompt, model construction, graph construction |
| `app/tools/customer_tools.py` | Five customer tools, bound to authenticated identity |
| `app/rag/` | Corpus validation, chunking, BM25, vectors, rank fusion |
| `app/evaluation/` | Benchmark schemas, isolated fixtures, runner and rubric |
| `app/observability/` | Structured events, request IDs and model/tool callbacks |
| `frontend/streamlit_app.py` | Authentication selection and workspace routing |
| `frontend/auth_pages.py` | Account forms and admin account management |
| `frontend/customer_workspace.py` | Customer chat history and email preferences |
| `frontend/reviewer_dashboard.py` | Queue, evidence, decisions, simulation and audit UI |
| `frontend/api_client.py` | Reviewer HTTP client and error handling |
| `scripts/` | Seed, ingest, admin bootstrap, email worker, login and evaluation CLIs |
| `alembic/versions/` | Five application schema migrations |
| `data/knowledge_base/` | Approved policies and version manifest |
| `data/evaluations/` | Versioned regression datasets |
| `tests/conftest.py`, `tests/helpers.py` | Shared test fixtures and workflow helpers |
| `docs/`, `DECISIONS.md` | Focused guides and architecture trade-offs |

HTTP handlers validate requests and translate service errors to HTTP responses.
Services coordinate business rules and transactions. Repositories encapsulate
database access. Agent tools call these application capabilities under a bound
customer identity. Frontend page selection never substitutes for API permissions.

## 4. Authentication, registration, roles, and sessions

### 4.1 Authentication modes

| Mode | Customer identity | Reviewer identity | Intended use |
| --- | --- | --- | --- |
| `local` | Signed local bearer token subject | Signed token with reviewer role | Main registration/login flow |
| `oidc` | Verified external bearer token subject | Verified token with reviewer realm role | Optional Keycloak integration |
| `demo` | Configured API key plus caller-supplied customer ID | Separately configured reviewer key | Controlled development and tests |

`.env.example` selects local mode. The Python settings fallback is demo mode, so
set `AUTH_MODE=local` explicitly. Switching modes neither migrates users nor
reassigns orders. Local UUIDs, OIDC subjects, and `demo-customer` are different
identities even if their email addresses look similar.

Local/OIDC API requests use `Authorization: Bearer ACCESS_TOKEN`. Demo customer
requests use `X-API-Key` and `X-Customer-ID`; reviewer requests use
`X-Reviewer-Key`. Configured reviewer keys must differ from the demo customer key.
Demo mode lets the caller choose customer identity and is unsuitable for public
customer authentication.

### 4.2 Local registration and login

1. A customer submits name, email and password through Register.
2. The backend normalizes the email and validates the request. Registration
   requires a 12–128 character password, a nonblank name up to 100 characters,
   and rejects extra fields such as a caller-supplied role.
3. The password is hashed with Argon2 via pwdlib. The account receives a UUID and
   the server-selected `customer` role. Plain passwords are not stored.
4. If email is enabled, account creation queues a verification email in the same
   transaction. Email-disabled accounts can still log in and use chat.
5. Login checks the password and returns a bearer token, profile and 1,800-second
   lifetime. Five failed password attempts cause a five-minute account lock.
6. Streamlit stores the session in its session state. It clears it on logout,
   expiry or API URL change; a changed chat identity starts a new UI conversation.

Local JWTs use HS256, issuer `supportflow-local`, audience `supportflow-api`, and
30-minute expiry. Required claims include subject, expiry, issued-at, issuer and
audience. Email verification status is embedded in the token: log in again after
verifying email to obtain refreshed claims.

The signing secret comes from `LOCAL_AUTH_SECRET` or a generated
`.local/auth-signing.key`. Explicit secrets must have at least 32 characters.
Keep the secret stable and consistent across API and worker processes. Rotation
invalidates existing local sessions and pending verification-code digests.
Tokens are stateless: logout clears the UI session but does not revoke an already
issued bearer token immediately.

### 4.3 Administrators and reviewer permissions

Public registration only creates customers. The first administrator is created by
the interactive `scripts.create_admin` CLI. It prompts for a password twice and
uses a PostgreSQL advisory transaction lock to serialize bootstrap attempts. It
refuses when an admin already exists.

Authenticated admins can create later admins/customers and list the latest 100
account profiles. Profiles exclude password hashes and verification secrets.
Local storage currently has `customer` and `admin` roles; an admin token contains
both `admin` and `reviewer`. A customer token contains only `customer`. Local
admins therefore access reviewer and account-management workspaces; they do not
automatically receive customer permissions.

### 4.4 Email verification

Verification uses a random six-digit code, valid for 15 minutes, with five guesses
per code. The account stores an HMAC-SHA256 digest bound to its ID. The pending
outbox contains the plaintext code so the worker can send it; the worker clears
that field after successful sending. The verification endpoint locks the account
and compares digests securely. Resending requires the account password and a
one-minute cooldown. Verification does not happen when the mail service is disabled.

### 4.5 Optional OIDC

The backend accepts RS256 access tokens from one configured issuer and JWKS URL.
It checks signature, key ID, issuer, audience, required time claims, subject and
realm roles. Subjects must fit the 40-character customer identifier. HTTP issuer
URLs require the explicit development setting `OIDC_ALLOW_HTTP=true`.

JWKS clients cache keys for 300 seconds and use a five-second fetch timeout.
Missing/invalid tokens return 401, absent roles return 403, and unavailable keys
can return 503. There is no fallback to demo headers after a token failure.
The supplied Keycloak development realm uses separate customer/reviewer roles.
Its admin-console account is distinct from application reviewer users.

The current OIDC UI uses pasted access tokens, with `scripts.login` providing
device authorization. The automatic email/password forms belong to local mode.

## 5. Frontend screens and behavior

Start the UI with `streamlit run frontend/streamlit_app.py`.

| Screen | Available behavior |
| --- | --- |
| Log in | Shared email/password form for local customers and admins |
| Register | Customer account creation; no public privileged-role selection |
| Verify email | Email and six-digit verification code |
| Resend verification | Email/password confirmation and resend request |
| Customer workspace | Chat input, message history and optional case email preferences |
| Reviewer dashboard | Status-filtered case queue, 25 records per page, refresh and case selection |
| Case review | Evidence snapshot, proposal, policy reference, review reason and approval amount |
| Approved case | Explicit confirmation checkbox followed by simulated execution |
| Audit/history | Ordered workflow events and advisory historical comparisons |
| Manage accounts | Admin-created customer/admin accounts and account profile table |

Local login routes admins to reviewer/account management and customers to chat.
Bearer tokens are attached internally; users do not copy tokens in this flow.
The sidebar allows the API URL to be set. `SUPPORTFLOW_UI_AUTH_MODE` can override
the UI's locally read authentication mode when the API is configured separately.

Customer case status is queried through chat; there is no dedicated customer case
list screen. The frontend does not push live case changes into an open chat.
The reviewer refresh control or another interaction reloads data. Logout/history
reset clears the visible session; it does not delete persistent graph checkpoints.

## 6. Chat processing, agent tools, and conversation memory

### 6.1 Request flow

```mermaid
sequenceDiagram
    participant U as Customer UI
    participant A as FastAPI
    participant G as LangGraph
    participant M as Groq model
    participant T as Customer tool
    participant D as Database / policy corpus
    U->>A: POST /v1/chat + bearer token
    A->>A: Verify customer role and bind subject
    A->>G: Invoke with customer_id:thread_id
    G->>M: Prompt + conversation + tools
    M-->>G: Tool call or final response
    G->>T: Execute bound customer tool
    T->>D: Owned query / investigation / retrieval
    D-->>T: Verified application facts
    T-->>G: Structured tool result
    G->>M: Continue with tool result
    M-->>G: Customer response
    G-->>A: Persisted state and final message
    A-->>U: answer + original thread_id
```

`ChatRequest` accepts a 1–4,000 character message and a 1–100 character thread ID.
The API constructs the actual checkpoint namespace as
`{authenticated_customer_id}:{supplied_thread_id}`. Reusing another customer's
thread ID therefore does not select that customer's conversation.

`build_graph` uses ChatGroq at temperature zero and LangGraph's
`create_react_agent`. The graph can alternate model and tool calls before
returning a final response. PostgreSQL checkpoints are initialized at API startup
and preserve state across invocations of the same namespaced thread. This is
conversation persistence, not autonomous learning or a separate long-term memory
ranking system. The current Streamlit session does not provide a saved-thread
browser for restoring arbitrary older conversations.

### 6.2 Tool inventory

| Tool | Input | Behavior |
| --- | --- | --- |
| `lookup_order` | `order_id` | Read only an order owned by the authenticated customer |
| `find_policy` | `question` | Retrieve versioned official policy passages |
| `report_delivery_issue` | `order_id`, `issue` | Open or reuse an active owned case and return workflow facts |
| `lookup_dispute` | `case_id` | Read an owned case's current customer-facing status |
| `lookup_order_dispute` | `order_id` | Find an active or latest closed owned case by order |

Customer identity and verified email are bound when the API constructs tools.
They are never model-supplied arguments. The tool collection contains no reviewer
approval, rejection or execution tool.

### 6.3 Response rules

The system prompt instructs the model to retrieve facts rather than invent order
states, identifiers, decisions, currencies or actions. It asks for an order ID
when absent; hypothetical questions and status requests should not create cases.
It requires current status lookups, distinguishes reused cases, cites policy
versions, and treats retrieved/customer text as data rather than instructions.

An approved case remains pending execution. A resolved simulation must be described
as moving no money. Notification claims depend on returned case configuration;
queued messages are not guaranteed delivery. Prompt instructions guide behavior
but are not a proof that every live model response is correct.

Currency metadata is absent. `amount_cents` is used as an integer minor-unit
field; do not infer a currency symbol or denomination from its name.

## 7. Investigation rules and case lifecycle

The delivery-dispute service snapshots the owned order, stored delivery evidence,
prior case IDs and deterministic decision. Customer allegations are recorded as
the issue; they do not become trusted carrier proof.

Current rule version: `delivery-dispute-v1`, source `delivery_dispute_policy.md`.
Rules are evaluated in this order:

| Condition | Proposed action | Missing information |
| --- | --- | --- |
| Order is not delivered | `shipping_review` | None |
| Delivered, but age is missing or negative | `investigate` | `delivery_age` |
| Delivery age exceeds seven days | `escalate` | None |
| No evidence or proof is not matched/mismatched | `investigate` | `verified_delivery_proof` |
| Proof is mismatched | `refund_review` | None |
| Proof is matched | `carrier_review` | None |

Every result sets `requires_human_review=true` and `payment_authorized=false`.
Cases start as `awaiting_investigation` when information is missing; otherwise
they start as `awaiting_review`. The proposal's action and the case's status are
different fields.

```mermaid
stateDiagram-v2
    [*] --> awaiting_review: Evidence sufficient
    [*] --> awaiting_investigation: Evidence incomplete
    awaiting_review --> approved: Eligible reviewer approval
    awaiting_review --> rejected: Reviewer rejection
    awaiting_investigation --> rejected: Reviewer rejection
    approved --> resolved: Simulated execution
```

Review accepts either pending state, but approval still requires a valid stored
refund proposal and current eligibility. There is no dedicated evidence-update,
reinvestigation, appeal or reopening endpoint. Editing evidence outside the app
does not automatically replace the original investigation snapshot.

The chat service locks the customer's order before finding or creating an active
case, so concurrent chat threads reuse the existing active case. The low-level
`POST /v1/cases` API deliberately creates a separate case per request and does
not offer that reuse guarantee. A rejected or resolved case is closed; a later
report can create another case, while refund execution remains protected per order.

Customer tool status includes proposal, missing information, policy source,
next step, review decision, approved amount, simulated refund and notification
availability. It omits internal reviewer notes. The raw owned-case HTTP detail
endpoint returns the stored investigation snapshot.

## 8. Review, execution, concurrency, and audit

### 8.1 Review

The reviewer submits `decision`, a nonblank reason up to 2,000 characters and an
approval amount when approving. The amount must be a strict positive integer;
booleans, zero and negative values are rejected. Rejection cannot include an amount.

The transaction locks the shared order and case, checks the pending state, and
validates approval against:

- Customer ownership matching the case.
- The stored proposal's current policy version and `refund_review` action.
- Current order age/status and current delivery proof still supporting refund review.
- Amount no greater than the current order total.
- No conflicting legacy refund request or already simulated refund.

It inserts one review per case, updates status, records a `review_recorded` event,
and queues the relevant status email if subscribed. A recorded review cannot be
overwritten by submitting another decision.

### 8.2 Execution

Execution requires an approved review. It takes the same order/case locks, checks
for an existing simulated refund, and revalidates eligibility and amount before
inserting a simulation. It then marks the case resolved, records
`refund_simulated`, and queues a resolution email in the transaction.

A repeat execution of the same completed case returns the existing refund ID with
`duplicate=true`. A different case for that already-refunded order is blocked.
Unique constraints on simulated-refund order and case IDs provide database-level
protection in addition to the locks. Audit-write failure rolls back execution and
status changes. These guarantees cover the local simulation; integrating a payment
provider would also require provider-side idempotency and reconciliation.

### 8.3 Legacy refund endpoint

`POST /v1/refunds` is retained separately. It requires `confirm=true` and creates
or returns a legacy `requested` refund record after basic ownership/eligibility
checks. It does not execute payments and is not an agent tool. It does not provide
the full reviewed dispute workflow. Both paths check for conflicting records;
reviewed cases with legacy requests require manual reconciliation. Use the case
workflow for the primary demonstration.

### 8.4 Audit

Case events contain actor, kind, details and timestamp, ordered by event ID.
Implemented kinds include `case_investigated`, `email_preference_initialized`,
`email_preference_changed`, `review_recorded` and `refund_simulated`.
The application appends events and exposes reviewer-only audit reads. There is
no cryptographic tamper proof or database-enforced immutability. SMTP delivery
attempts are tracked in the outbox and operational logs rather than as a case
audit event for every attempt.

## 9. Policy retrieval and historical case comparison

### 9.1 Approved corpus and ingestion

The corpus contains shipping, refund, cancellation and delivery-dispute Markdown
policies. `manifest.json` maps each policy filename to a version. Loading validates
that every Markdown file is represented, filenames are local basenames, versions
are nonblank and policy content is nonempty.

Documents are split into approximately 900-character passages, preferring a word
boundary. Each has a full document SHA-256 and a deterministic 24-character chunk
ID derived from source, version, document hash and chunk index. Citation format:

```text
source_filename@version#chunk_id
```

`scripts.ingest` upserts chunks and embeddings into the persistent
`support_policy_chunks_v1` Chroma collection and removes stale chunk IDs.
The embedding model may require a first-use download; lexical ranking does not.

### 9.2 Query pipeline

1. Load and validate current corpus chunks.
2. Normalize lexical terms with aliases and stopwords.
3. Rank up to ten BM25 candidates (`k1=1.5`, `b=0.75`).
4. Query up to ten Chroma cosine candidates when vectors are available.
5. Exclude vector results outside the current corpus or beyond distance `0.65`.
6. Merge lexical/vector rankings with reciprocal rank fusion: each method
   contributes `1 / (60 + rank)`.
7. Return three passages by default; allowed result limits are one through ten.

Each result includes text, source, version, chunk ID, hash, citation, ranking score,
retrieval methods and vector availability. Vector errors/empty collections allow
lexical fallback. There is no cross-encoder reranker or semantic entailment
verification stage. Ranking scores are not confidence or authorization. Policy
text and Python decision rules must be kept aligned when policy changes.

### 9.3 Similar resolved cases

Reviewer suggestions consider up to 200 recent eligible completed simulations
from other orders, with approved reviews, matching refund amounts and the current
policy version. Historical evidence is reevaluated under current rules.

Comparison uses weighted structured features: proof status 3, proposed action 3,
order status 1, delivery window 1 and amount band 1. Proof and proposed action
must match to be comparable. The score is matched weight divided by total weight;
it is not an outcome probability. Amount bands are up to 10,000, 10,001–100,000,
and above 100,000 integer minor units.

Responses default to three examples, with a maximum requested limit of ten, and
include matching features, differences and whether the candidate pool was
truncated. This is explainable advisory comparison, not vector case retrieval,
automatic retraining, or evidence that a customer was satisfied.

## 10. Database schema and migrations

| Table | Main fields | Constraints / purpose |
| --- | --- | --- |
| `accounts` | ID, name, email, password hash, role, failed logins, lock deadline, verification state/digest/expiry/attempts/sent time, created time | Unique email; local credentials |
| `orders` | ID, customer ID, status, amount, delivery age | Customer ID indexed; owner identifier is not an account foreign key |
| `delivery_evidence` | Order ID, tracking JSON, proof status, source | Order ID is primary/foreign key; one evidence record per order |
| `dispute_cases` | ID, order ID, customer ID, issue, status, investigation JSON, created time | Order foreign key; customer ID indexed |
| `case_reviews` | Case ID, reviewer ID, decision, reason, amount, created time | Case primary/foreign key; at most one recorded review |
| `simulated_refunds` | ID, order ID, case ID, amount, created time | Order and case each unique and foreign-keyed |
| `refunds` | Integer ID, order ID, customer ID, requested status, created time | Legacy path; order unique |
| `case_events` | Integer ID, case ID, actor, kind, details JSON, created time | Case foreign key/index; ordered application history |
| `email_subscriptions` | Case ID, customer ID, recipient, delivery mode, enabled, updated time | One preference per case |
| `email_outbox` | ID, nullable case ID, customer ID, recipient, delivery mode, kind, status, attempts, retry time, error type, verification code, timestamps | Unique case/kind for case mail; account verification uses null case ID |

The investigation JSON stores order and delivery snapshots, previous case IDs and
the deterministic decision. State snapshots preserve the basis for a proposal;
approval/execution also inspect current data to avoid trusting stale eligibility.
Reviewer/customer identifiers support demo, local and OIDC sources; they are not
all foreign keys into `accounts`.

Application migrations:

| Revision | Introduces |
| --- | --- |
| `0001_initial` | Orders and legacy refunds |
| `0002_dispute_cases` | Delivery evidence and dispute cases |
| `0003_resolutions` | Reviews, simulated refunds, case events |
| `0004_email_notifications` | Email subscriptions and outbox |
| `0005_accounts` | Local accounts and verification-mail support |

Run `alembic upgrade head` for application tables. LangGraph's checkpointer calls
its own idempotent setup at API startup. Keep applied migration files intact.

## 11. Email notifications and delivery guarantees

### 11.1 Enrollment and event creation

When real SMTP mode is enabled and a local/OIDC customer has a verified email,
opening or reusing a case automatically initializes its subscription. An existing
preference—including opt-out—wins. The model never supplies a recipient address.
Local Mailpit case subscriptions can be configured manually for testing.

Approval, rejection and simulation completion enqueue `case_approved`,
`case_rejected` and `case_resolved` respectively. Case creation itself does not
send a dedicated case-created email. Account creation/resend queues
`verify_account` when enabled. Opting in later does not backfill past transitions.

SMTP subscription endpoints require the token's verified account email and reject
an alternate recipient. Demo authentication cannot enroll external SMTP case mail.
Subscription changes require case ownership and record a preference audit event.

### 11.2 Dispatch and retries

By default, API startup creates an asynchronous dispatcher when both
`EMAIL_ENABLED` and `EMAIL_WORKER_IN_API` are true. It handles bounded batches of
up to ten records, then waits up to five seconds. A standalone
`python -m scripts.email_worker --watch` is available when operating separately.

The worker locks due pending rows with `FOR UPDATE SKIP LOCKED`, validates the
subscription or verification code again, and sends SMTP in a worker thread.
Disabled, changed or obsolete recipients/modes/codes are skipped. SMTP successes
are marked sent; failures store the exception type rather than sensitive provider
text. Retries use `min(30 * 2**attempts, 3600)` seconds, with failure terminal after
five attempts. There is no built-in failed-mail management/requeue UI.

States include pending, sent, skipped and failed. A stable outbox-based Message-ID
is supplied. Delivery is at least once: if SMTP accepts mail but the transaction
does not commit, a retry can send a duplicate. Unique queued events do not imply
exactly-once external delivery. Provider acceptance also does not guarantee inbox
arrival; bounce processing and delivery webhooks are not implemented.

### 11.3 SMTP modes

| Mode | Behavior |
| --- | --- |
| `local` | Restricted to localhost, 127.0.0.1 or mailpit; captured messages only |
| `smtp` | STARTTLS required, optional configured SMTP login, actual external transport |

The transport uses a ten-second connection timeout and a standard verified TLS
context. It implements SMTP plus STARTTLS, not implicit SMTPS on port 465.
Brevo SMTP uses its SMTP credentials; an API key for an HTTP API is a different
integration and is not used by this transport.

## 12. Complete HTTP API reference

All application routes have the `/v1` prefix. Swagger UI is `/docs`, schema is
`/openapi.json`. There is no root `/` route.

| Method | Endpoint | Access / purpose |
| --- | --- | --- |
| GET | `/v1/health` | Public liveness response; not a dependency readiness check |
| GET | `/v1/auth/config` | Public active authentication mode |
| POST | `/v1/auth/register` | Public, local mode; customer registration |
| POST | `/v1/auth/login` | Public, local mode; email/password login |
| POST | `/v1/auth/verify-email` | Local mode; email/code verification |
| POST | `/v1/auth/resend-verification` | Local mode; credentials and cooldown |
| POST | `/v1/auth/admins` | Local admin; create admin |
| POST | `/v1/auth/users` | Local admin; create customer |
| GET | `/v1/auth/users` | Local admin; latest 100 profiles |
| GET | `/v1/me` | Customer; authenticated subject and mode |
| GET | `/v1/orders/{order_id}` | Customer; owned order details |
| POST | `/v1/chat` | Customer; agent conversation |
| POST | `/v1/cases` | Customer; create a new owned case, 201 |
| GET | `/v1/cases/{case_id}` | Customer; owned investigation snapshot |
| GET | `/v1/cases/{case_id}/email-subscription` | Customer; owned email preference |
| PUT | `/v1/cases/{case_id}/email-subscription` | Customer; enable/disable preference |
| POST | `/v1/refunds` | Customer; legacy confirmed request, no payment |
| GET | `/v1/reviewer/cases` | Reviewer; filter by status, limit 1–100, offset >= 0 |
| GET | `/v1/reviewer/cases/{case_id}` | Reviewer; case and recorded review |
| POST | `/v1/reviewer/cases/{case_id}/review` | Reviewer; approve/reject |
| POST | `/v1/reviewer/cases/{case_id}/execute` | Reviewer; execute approved simulation |
| GET | `/v1/reviewer/cases/{case_id}/audit` | Reviewer; ordered events |
| GET | `/v1/reviewer/cases/{case_id}/similar` | Reviewer; advisory comparison, limit 1–10 |

Representative request bodies:

```json
{"name":"Example Customer","email":"customer@example.com","password":"replace-with-a-long-password"}
```

```json
{"message":"USER1-1001 says delivered, but I did not receive it. Please investigate.","thread_id":"demo-thread-1"}
```

```json
{"order_id":"USER1-1001","issue":"Marked delivered but not received"}
```

```json
{"decision":"approve","reason":"Reviewed conflicting delivery proof","amount_cents":299900}
```

```json
{"decision":"reject","reason":"Insufficient grounds for the proposed refund"}
```

```json
{"enabled":true}
```

The final subscription example is for real SMTP with a verified token email;
local capture also needs an `email` value. Execution has no request body.
Chat responds with `answer` and the caller's `thread_id`. Execution responds with
`refund_id`, `case_id`, `amount_cents`, `status: "simulated"` and `duplicate`.

Typical errors: 401 invalid/missing account credentials, 403 missing permissions,
404 unknown/not-owned resource or disabled local-auth route, 409 workflow conflict,
422 validation/amount failure, 429 login/resend/provider limits where applicable,
and 503 unavailable configuration/provider. Demo reviewer failures return 403.
Owned resources return not found rather than revealing another customer's data.

## 13. Configuration reference

Settings load environment values and `.env`, ignore unknown fields and are cached.
Restart processes after changing configuration. The following are code defaults,
not a report of private active credentials.

| Variable | Default / meaning |
| --- | --- |
| `GROQ_API_KEY` | Empty; required for hosted chat |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `DATABASE_URL` | Async SQLAlchemy PostgreSQL URL; host default 127.0.0.1:5433 |
| `CHECKPOINT_DATABASE_URL` | psycopg PostgreSQL URL for checkpoints; same host default |
| `CHROMA_PATH` | `.local/chroma` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` |
| `AUTH_MODE` | Code fallback demo; example configuration selects local |
| `LOCAL_AUTH_SECRET` | Empty means generated local signing file |
| `API_KEY` | Empty; configured customer demo key |
| `REVIEWER_API_KEYS` | Empty mapping; demo reviewer-name to separate secret |
| `OIDC_ISSUER` | Empty; trusted issuer for OIDC |
| `OIDC_AUDIENCE` | `supportflow-api` |
| `OIDC_JWKS_URL` | Empty; configured external signing keys |
| `OIDC_ALLOW_HTTP` | false; development-only HTTP allowance |
| `EMAIL_ENABLED` | false |
| `EMAIL_WORKER_IN_API` | true |
| `EMAIL_DELIVERY_MODE` | local |
| `SMTP_HOST` | 127.0.0.1 |
| `SMTP_PORT` | 1025 |
| `SMTP_STARTTLS` | true; enforced for external SMTP |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Empty; provider SMTP credentials |
| `EMAIL_FROM` | supportflow@localhost; replace for real SMTP |
| `SUPPORTFLOW_UI_AUTH_MODE` | Optional frontend environment override |
| `SUPPORTFLOW_TEST_DATABASE_URL` | Optional dedicated PostgreSQL test target |
| `KEYCLOAK_ADMIN_PASSWORD` | Required by optional identity Compose profile |

Development database URLs:

```dotenv
DATABASE_URL=postgresql+asyncpg://supportflow:supportflow@127.0.0.1:5433/supportflow
CHECKPOINT_DATABASE_URL=postgresql://supportflow:supportflow@127.0.0.1:5433/supportflow
```

Illustrative Brevo SMTP configuration:

```dotenv
AUTH_MODE=local
EMAIL_ENABLED=true
EMAIL_WORKER_IN_API=true
EMAIL_DELIVERY_MODE=smtp
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=YOUR_BREVO_SMTP_LOGIN
SMTP_PASSWORD=YOUR_BREVO_SMTP_KEY
EMAIL_FROM=YOUR_VERIFIED_SENDER_ADDRESS
```

These are configuration values, not a guarantee of any provider's current plan
limits or sender eligibility. Keep actual credentials in private configuration.

## 14. Local setup and demonstration walkthrough

### 14.1 Install and initialize

Run from the repository root in PowerShell. Prerequisites: Python 3.11/3.12,
Docker with Compose, and a Groq key for live chat.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
```

On a new checkout only, copy `.env.example` to `.env`. Do not overwrite an existing
configured `.env`. Set `AUTH_MODE=local`, `GROQ_API_KEY` and desired email settings.

```powershell
docker compose up -d db
alembic upgrade head
python -m scripts.ingest
python -m scripts.create_admin --email admin@example.com --name "Administrator"
```

Use a real address you control for external verification. The admin command is a
first-admin bootstrap; later runs intentionally refuse if an admin already exists.

### 14.2 Start the application

Separate activated terminals:

```powershell
uvicorn app.main:app --reload
```

```powershell
streamlit run frontend/streamlit_app.py
```

Open `http://localhost:8501`. API docs are `http://localhost:8000/docs` and liveness
is `http://localhost:8000/v1/health`. Startup needs a reachable checkpoint database.

### 14.3 Seed orders for the actual customer

Register a customer, verify email if enabled and log in again. Find the UUID in
admin account management or through customer-authenticated `GET /v1/me`.

```powershell
python -m scripts.seed --customer-id CUSTOMER_UUID --order-prefix USER1
```

| Seeded order | State | Amount in minor units | Delivery age / evidence |
| --- | --- | --- | --- |
| `USER1-1001` | delivered | 299900 | Three days; mismatched simulated delivery proof |
| `USER1-1002` | shipped | 159900 | No delivery age/evidence supplied |
| `USER1-1003` | delivered | 499900 | Fourteen days; outside dispute window |

The default seeder uses `ORD-*` and owner `demo-customer`. Those orders do not
belong to newly registered accounts. A prefix already owned by someone else is
rejected; choose a unique alphanumeric prefix. Seeding is additive for existing
records, not a reset of modified orders or resolved cases.

### 14.4 Demonstrate the complete flow

1. Customer: report that `USER1-1001` was marked delivered but never received.
2. Agent: call the issue-report tool, receive an `awaiting_review` case with
   `refund_review`, and explain that review is required.
3. Customer: report it again; the chat path should find/reuse the active case.
4. Admin in another browser session: open the reviewer dashboard, inspect the
   evidence snapshot, policy reference and audit events.
5. Approve with a reason and an amount no greater than 299900, or reject with a reason.
6. After approval, use the explicit execution confirmation and execute simulation.
7. Customer: ask for status; approved means pending execution, resolved means the
   simulation completed with no money moved.
8. If subscribed and enabled, inspect approval/rejection/resolution email delivery.
9. Repeating execution through the API should return the same refund ID as a duplicate.

### 14.5 Free local email capture

```powershell
docker compose -f docker-compose.yml -f docker-compose.email.yml up -d mailpit
```

```dotenv
EMAIL_ENABLED=true
EMAIL_DELIVERY_MODE=local
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
EMAIL_FROM=supportflow@localhost
```

Restart the API. View captured mail at `http://localhost:8025`. Registration codes
can be delivered there. Configure a case subscription manually for local status
mail; automatic real-address enrollment applies to SMTP mode. Mailpit messages
do not reach the recipient's real inbox.

### 14.6 Optional Keycloak startup

Set a private `KEYCLOAK_ADMIN_PASSWORD`, then start the optional service:

```powershell
docker compose -f docker-compose.yml -f docker-compose.auth.yml up -d keycloak
```

At `http://localhost:8080/admin`, configure application users in the imported
supportflow realm and assign customer/reviewer roles. Configure OIDC issuer,
audience and JWKS, set `AUTH_MODE=oidc`, then restart the application.

```powershell
python -m scripts.login --output .local/customer-token.json
```

Complete device login and use the access token in the OIDC UI. Use a separate
reviewer login/token. Existing local accounts and their order ownership are not
converted. The Keycloak service is development infrastructure, not a hardened
public identity deployment.

## 15. Deployment and persistence

The main Compose file defines PostgreSQL and the API. Host PostgreSQL port is
5433, while containers use `db:5432`. The API container overrides its application
and checkpoint database URLs accordingly. Its startup command applies migrations,
seeds default demo orders, ingests policies and starts Uvicorn on port 8000.
It does not start the Streamlit frontend or bootstrap local admins automatically.

Named volumes retain PostgreSQL data (`pgdata`) and API `.local` data (`chromadata`).
The optional Keycloak service has a separate data volume. Host `.local` storage and
container `.local` volumes are different locations; signing keys and Chroma data
must be consistent with the process that uses them. A host bootstrap command and
container API/worker must share `LOCAL_AUTH_SECRET` when relying on local account
verification digests across those processes.

Host-run SMTP uses 127.0.0.1; container-run API reaching Mailpit uses `mailpit` on
the shared Compose network. OIDC issuer must match the token's externally visible
issuer even when JWKS are fetched using an internal container hostname.

Persistent state includes application rows, graph checkpoints, signing keys,
email outbox and evaluation reports. Keep migrations and state when cleaning code.
Public deployment additionally needs HTTPS, secrets management, backups, retained
storage, controlled network exposure and appropriate request/resource limits.

## 16. Testing, evaluation, and observability

### 16.1 Automated checks

```powershell
pytest -q
pytest --postgres -q
ruff check app tests scripts frontend alembic
ruff format --check app tests scripts frontend alembic
python -m scripts.evaluate
python -m scripts.evaluate_retrieval
```

Retrieval evaluation defaults to offline keyword ranking. Run
`python -m scripts.evaluate_retrieval --vectors` to measure hybrid ranking against
the local Chroma collection; this can download the embedding model. Its metrics
measure source-level ranking on the small corpus, not answer correctness.

The suite covers policy decisions, ownership, role isolation, local/OIDC tokens,
account verification, case reuse/status, approval/rejection, amount limits,
simulation duplicates, rollback, email processing, retrieval, frontend behavior
and telemetry. SQLite-backed integration fixtures isolate most HTTP tests from
external services. Optional PostgreSQL checks use disposable schemas to test
real locking/concurrency; use `SUPPORTFLOW_TEST_DATABASE_URL` for a dedicated DB.

GitHub Actions runs lint, formatting, offline tests, policy/retrieval evaluations,
compilation and a separate PostgreSQL 16 concurrency job. Reports are uploaded as
artifacts. CI does not make live Groq calls by default.

Latest cleanup verification on this checkout: **97 tests passed**, **10/10 policy
scenarios passed**, and offline keyword retrieval hit@1, recall@3 and reciprocal
rank were all 1.0.
These are recorded regression results on small datasets, not production accuracy
claims or proof of all live-model behavior. LangGraph currently emits deprecation
warnings for `create_react_agent`; migration to the newer agent API remains work.

### 16.2 Agent evaluation

The default `data/evaluations/support_v2.json` includes ten policy and thirteen
agent scenarios. Live model testing is explicit:

```powershell
python -m scripts.evaluate --mode agent --live
python -m scripts.evaluate --mode agent --live --scenario unknown-order-owner
python -m scripts.rescore .local/evaluations/YOUR_REPORT.json
```

Live evaluation uses the production system prompt with isolated in-memory tools,
fresh graphs, bounded steps and a 45-second scenario timeout. It makes hosted
model calls but does not open real DB cases or move money. Scenarios cover missing
IDs, hypothetical questions, ownership denial, current status, active case reuse,
incomplete evidence, approval versus execution, rejection, simulation, notification
claims and approval injection.

Rubric `support-rubric-v3` checks tool selection/arguments/execution, required
response facts, forbidden claims and nonempty responses. Regex and normalization
checks are heuristics; they can miss paraphrases or misread negations. Execution
errors are separated from completed behavioral failures; overall pass rate still
includes errors. Reports record model/prompt/dataset fingerprints, responses,
tool traces, available token usage, latency and check outcomes. No provider cost
estimate is calculated. Rescoring reuses saved inference and cannot demonstrate
that a changed prompt improves future model outputs.

Reports are timestamped under `.local/evaluations`. The earlier 11/13 live result
is a historical measurement, not a current guarantee. Run the full live benchmark
again to measure the currently configured model/prompt.

### 16.3 Operational telemetry

Every HTTP request receives a generated `X-Request-ID`. Structured events include
timestamp, request ID, route template, method, status, latency and exception type.
Agent callbacks count model/tool calls, errors, latency and token usage when
available. Retrieval reports candidate counts and vector availability; email
reports delivery outcome, attempt count and error type.

Operational callbacks intentionally omit prompts, tool arguments, tool outputs,
customer text and email bodies. Business audit records and checkpoints do contain
application/conversation data; this content-free logging design does not imply
the database contains no personal information. Evaluation reports can also hold
model responses and fixture tool arguments.

Groq rate limits map to 429 with a bounded `Retry-After`; provider connection,
timeout/status failures map to 503. Initialization errors return a generic 503;
unexpected chat errors return a generic 500 with request-ID guidance. There is
no automatic provider fallback, centralized tracing backend, alerting system or
operational metrics dashboard supplied by the repository.

## 17. Troubleshooting

| Symptom | Explanation / check |
| --- | --- |
| `GET /` returns 404 | Expected; use `/docs` or `/v1/health` |
| Reviewer endpoint returns 401 | Missing, expired, wrong-mode or invalid bearer token; log in again |
| Reviewer endpoint returns 403 | Account lacks reviewer permissions; demo mode also requires a configured reviewer key |
| Customer gets order not found | Check exact ID and ownership; seed orders for the signed-in UUID/subject |
| `ORD-1001` invisible after registration | Default order belongs to demo-customer, not the new account |
| Registration page absent | Set AUTH_MODE=local for API/UI and restart; check UI override |
| Admin cannot use `/v1/me` | Local admin token has reviewer/admin roles, not customer |
| Verification worked but emails still disabled | Log in again to refresh token claims; confirm SMTP mode/service/subscription |
| Email worker processes zero records | No due pending events, service disabled, or worker connected to another DB |
| Approval/rejection email missing | Check subscription existed at transition, verified token, delivery mode and outbox status |
| STARTTLS not supported | Check SMTP host/port; Mailpit capture uses local mode, external STARTTLS transport typically uses its configured submission port |
| Mail marked sent but inbox empty | SMTP acceptance is not inbox delivery; inspect provider sender configuration and spam/bounce information |
| Verification fails after process change | Ensure API/worker/bootstrap share signing secret and code has not expired or been replaced |
| Approval conflicts | Check stored/current policy, proof, age, amount, state and legacy/refund records |
| Repeating case creation adds cases | Raw POST /cases creates new cases; chat report tool reuses active cases |
| Search uses keyword only | Inspect vector_status, run ingestion, verify Chroma path/model availability |
| Groq 429 | Wait for Retry-After; rerun affected evaluation scenario if needed |
| API startup fails | Check checkpoint DB connectivity and schema/setup permissions |

## 18. Implemented boundaries and remaining work

Implemented: account registration/login and verification, role checks, owned
orders/cases, tool-using chat, persistent graph state, deterministic proposals,
reviewer dashboard, separate approval/execution, simulated refund idempotency,
audit history, hybrid policy retrieval, advisory case comparisons, transactional
email outbox, automatic dispatch, regression evaluations and structured telemetry.

Not implemented as complete product capabilities:

- Real carrier, commerce or payment-provider integrations and reconciliation.
- Evidence upload/edit, automatic reinvestigation, appeal/reopening and reviewer assignment.
- Dynamic planners or multiple specialist agents; investigation uses stored evidence and fixed rules.
- Semantic answer-entailment verification, learned reranking or autonomous self-learning.
- Customer case list, saved-conversation browser, push updates or polished production frontend.
- Password reset, account deletion, refresh tokens, MFA and immediate session revocation.
- Email bounce/webhook handling, guaranteed delivery and a failed-message operations UI.
- Comprehensive tenant isolation, configurable enterprise approval hierarchies and full account audit.
- Enforced retention/deletion policies, production backups, deployment monitoring and load validation.

The next changes should retain these boundaries: the backend owns authorization
and policy, the model explains verified facts, review is distinct from execution,
and external side effects require explicit idempotency and auditable outcomes.

## 19. Voice channel (new implementation)

The optional voice implementation adds `WS /v1/voice` and a microphone page at
`GET /v1/voice`, linked from the Streamlit customer workspace. It uses local
faster-whisper ASR, per-connection Silero VAD and the same authenticated customer
LangGraph agent, tools and PostgreSQL checkpointer as typed chat. There is no
second agent and no approval/execution tool exposed to voice callers.

Input is mono 16 kHz PCM16, 512 samples per binary frame, sent after an authenticated
start message. The graph responds in the selected language, preserving identifiers.
Final text is synthesized in bounded sentence-sized chunks and streamed as WAV
events. English/Hindi Piper models form the lightweight profile. ASR accepts
English, Hindi, Marathi, Tamil and Telugu; output languages require configured
Piper voices or the optional, separately installed AI4Bharat Indic-Parler adapter.
The interface lists configured output languages, not an unsupported-language claim.

New sustained speech cancels the pending graph task, signals speech-model work
and clears browser playback. Current native inference may finish a chunk in the
background, but its result is discarded. Committed customer-tool actions are not
undone by interruption. Speech is segmented with pre-roll and silence detection;
buffers, jobs, connection count and turn duration are bounded.

Install `pip install -e '.[dev,voice]'`, run `python -m scripts.prepare_voice`,
merge the generated `.local/voice/settings.env` values into `.env`, restart the
API and open the voice page. Models stay in ignored local storage and no schema
migration is required. The separate page uses customer login in local mode.
It needs localhost/HTTPS microphone permission; use headphones to reduce echo.

Completed turns expose ASR, agent, synthesis, endpointing, first-audio-send and
turn-completion timings. Download measurements from the page and summarize them
with `python -m scripts.evaluate_voice --turns EXPORTED_JSON`. These server-boundary
metrics exclude downstream network transit and final playback duration, and should
not be described as measured mouth-to-ear latency.

`data/evaluations/voice/manifest.example.json` supplies English/Hindi reference
utterances. Record consented human WAV samples into a private directory and run
`python -m scripts.evaluate_voice --manifest MANIFEST_JSON --run-asr` for per-language
corpus WER. Missing samples count as failures. Synthetic or mocked samples do not
establish human accuracy. The live channel does not store raw recordings, but its
transcripts remain subject to the normal chat/checkpoint/provider data flow.

Full protocol, limits, language/model setup and measurement definitions are in
`docs/voice.md`. Indic-Parler access/quality and real microphone performance require
separate live validation; they are not established by protocol integration tests.
Initial English/Hindi synthetic measurements, including the cold-start outlier,
are recorded in `docs/voice-validation.md`. The expanded suite passes 114 tests;
human-speech WER and subjective microphone quality remain unmeasured.
