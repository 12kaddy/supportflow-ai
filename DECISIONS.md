# Architecture decisions

## Modular FastAPI backend
Keep routes, schemas, services, persistence, and agent tools separate. The agent
uses application services rather than duplicating authorization or business rules.

## Authentication
Local database accounts provide the primary registration and login flow. Passwords
are hashed with Argon2; signed access tokens identify users and their roles.
Customer registration cannot grant reviewer or admin permissions. Bootstrap the
first admin through the CLI; administrative APIs manage privileged accounts.
OIDC remains an optional integration. Demo headers are for local demonstrations.

## Agent and policy boundaries
Groq supplies inference and LangGraph orchestrates tool use and durable conversation
state. Deterministic application rules produce delivery-dispute proposals.
Reviewer decisions are recorded separately from refund execution. Agent text never
constitutes approval or proof that a refund was executed.

## Transactions and audit
PostgreSQL stores orders, evidence, cases, reviews, simulated refunds, accounts,
notification preferences, and audit events. Transaction boundaries, row locks, and
unique constraints protect refund execution against duplicate requests.
Keep Alembic migrations as the schema history.

## Retrieval and case history
Policy retrieval combines keyword and vector search with versioned document
metadata and citations. Similar resolved cases provide advisory context; they do
not override current policies or authorize actions.

## Email delivery
Case decisions enqueue email events for a separate worker. SMTP credentials stay
in environment configuration. Delivery is retryable and at least once: a provider
acceptance followed by a worker crash can cause a duplicate email. Local Mailpit
supports development without sending external email.

## Verification
Offline tests cover authorization, workflow transitions, rollback behavior,
retrieval, accounts, and notifications. Optional PostgreSQL tests exercise
concurrent execution in disposable schemas. Agent evaluations supplement tests;
heuristic checks and mocked models do not establish live-model reliability.

## Current boundaries
Refunds and delivery evidence are simulated. Real payment and carrier adapters,
operational deployment hardening, and broader live evaluations remain separate
work. Preserve explicit customer ownership checks and human review when adding
external integrations.

