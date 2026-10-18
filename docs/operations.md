# Operations and tracing

API responses include a server-generated `X-Request-ID`. The server writes JSON
telemetry to stderr when the application starts. Use that ID to correlate:

- `http_request_completed`: method, route template, status, and elapsed time.
- `agent_tool_completed`: tool name, elapsed time, and success/error outcome.
- `chat_completed`: elapsed time, model/tool call counts, errors, and available tokens.
- `chat_initialization_failed`: the error type when chat cannot be configured.

These telemetry events omit customer messages, model responses, tool arguments and
outputs, query strings, customer/thread IDs, API keys, and raw exception messages.
Route templates are logged rather than case or order URLs. Token usage is `null`
when the provider does not supply it; no monetary cost is inferred. Tool errors
include exceptions and tools returning an error JSON object. Callback errors and
provider usage availability can limit observed metrics; these logs are operational
telemetry, separate from the transactional case audit trail.

Groq rate limits produce HTTP 429 with `Retry-After`; connection, timeout, and
other provider API failures produce HTTP 503. Unexpected chat failures return a
generic HTTP 500 with a request ID. Initialization failures return HTTP 503.
Provider exception text is not returned. Chat invocations are not automatically
replayed after failure because earlier tools may already have committed a case.
The provider SDK can perform its own transport retries; these are not separate
graph invocations or separately counted model calls. Retry a report after the
delay: its customer-scoped tool reuses an active case.

Telemetry uses application logs, without a separate log storage service or metrics dashboard.
Log retention and third-party logger configuration remain deployment concerns.
Restart the API to enable the middleware and callbacks.
