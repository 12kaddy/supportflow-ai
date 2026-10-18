# Resolution workflow

## Customer cases

Customers report delivery issues in chat. `report_delivery_issue` checks ownership,
looks up existing active cases, and stores an investigation snapshot when needed.
The snapshot contains order details, delivery evidence, previous case references,
and a versioned deterministic proposal. Status tools read current database state.

| Proposal | Typical trigger |
| --- | --- |
| `shipping_review` | Order is not marked delivered |
| `investigate` | Missing delivery age or inconclusive proof |
| `refund_review` | Conflicting proof within the seven-day request window |
| `carrier_review` | Matching delivery proof |
| `escalate` | Request outside the standard window |

A proposal is not authorization. Investigation snapshots do not automatically
refresh when stored carrier evidence changes. Review and execution independently
validate the current order, evidence, and policy.

## Review and simulation

Local-account admins use the reviewer dashboard. Optional OIDC reviewer accounts
use the same reviewer endpoints. Customer credentials cannot access these routes.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/reviewer/cases` | Filtered queue, 25 cases per page by default |
| `GET /v1/reviewer/cases/{id}` | Evidence and recorded review |
| `POST /v1/reviewer/cases/{id}/review` | Approve or reject once |
| `POST /v1/reviewer/cases/{id}/execute` | Execute the approved simulation |
| `GET /v1/reviewer/cases/{id}/audit` | Investigation, review and execution history |
| `GET /v1/reviewer/cases/{id}/similar` | Advisory historical examples |

Approval body:

```json
{"decision":"approve","reason":"Conflicting proof verified","amount_cents":10000}
```

Rejection body:

```json
{"decision":"reject","reason":"Insufficient evidence"}
```

Amounts use integer minor units without assuming a currency. Approval requires a
current refund-review proposal and an amount within the order total. Reviews are
final; changing a recorded review is not supported. Rejections cannot execute.

Order locks serialize competing cases and refund requests. Unique constraints
provide additional duplicate protection. Repeated execution of one case returns
the original simulated refund with `duplicate=true`; another case on the same
order returns a conflict. A partial refund consumes the order's single refund slot.

State changes, audit events and notification events commit together. Email delivery
runs separately. Audit events are append-only through the application; database
administrators can still alter them. The older `POST /v1/refunds` route records a
manual-review request and does not execute payment. Legacy requests and simulated
refunds block conflicting workflows for manual reconciliation.

## Similar historical resolutions

Suggestions compare structured proof, proposal, order status, delivery window and
amount band against up to 200 recent completed simulations for other orders.
Candidates need an approved review, a corresponding simulation, and current-policy
compatibility. Matching proof and proposal are mandatory. Results explain matching
features and differences without exposing historical customer details or notes.

The feature-match score is not an outcome probability. Historical simulations
establish neither customer satisfaction nor refund entitlement. Suggestions are
read-only and never update policy or authorize the current case.

## Persistence and tests

PostgreSQL stores accounts, cases, evidence, reviews, simulated refunds, audit
events, subscriptions and email outbox records. LangGraph maintains its own
checkpoint tables. Customer IDs scope order/case access and chat thread namespaces.

`pytest --postgres -q` creates a random isolated schema per test, exercises real
locking and JSON queries, and drops only that schema. It requires schema-creation
permission on the selected test database. Interrupted processes may leave a
temporary test schema behind. No live Groq credentials are needed.
