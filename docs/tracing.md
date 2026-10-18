# Local Phoenix tracing and debug replay

```powershell
pip install -e '.[dev,tracing]'
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d phoenix
```

Set these values and restart the API:

```dotenv
TRACING_ENABLED=true
TRACING_ENDPOINT=http://127.0.0.1:6006/v1/traces
TRACING_PROJECT=supportflow
TRACING_POLICY_TEXT=false
```

Open `http://localhost:6006`. For a containerized API on the shared network, use
`http://phoenix:6006/v1/traces`. The profile binds to loopback and persists data in
`phoenix_data`. It does not add public authentication/TLS, retention or backups.
Development images use `latest`; pin a digest for a reproducible deployment.

Custom OpenTelemetry callbacks produce OpenInference-compatible spans:

- `supportflow.turn`: provider/model, HTTP request ID when available, input checks,
  redaction counts, claim counts and rewrite decisions.
- `model.call`: one span per invocation, elapsed time and reported token counts.
- `tool.NAME`: tool timing and domain/error outcomes.
- `tool.find_policy`: chunk IDs, sources, versions, citations, ranking metadata,
  retrieval methods and vector availability.

`TRACING_POLICY_TEXT=true` also exports retrieved approved-policy passage text.
Raw customer prompts, tool arguments/results, account records, tokens, generated
answers and provider exception text are not exported by this callback. Policy text
can itself be confidential in your own corpus; leave the setting off if needed.
Model/tool spans are children of the turn span. Text, voice and enabled agent
evaluation runs use the integration. Missing token usage is unavailable, not zero.
Disabled tracing does not require the exporter package. API shutdown flushes spans.

## Concrete debugging story

```powershell
python -m scripts.trace_replay
```

This is a **scripted regression replay**, not a claimed spontaneous production
incident. The actual LangGraph case tool returns `approved` with execution pending;
the scripted model deliberately says, "Your refund has been issued."

The trace records one claim violation before verification, zero after, and a rewrite.
The fix renders verified case facts, explicitly says execution is pending, and
replaces the same assistant message in the checkpoint. An integration test verifies
that only one tool execution happened: no retry/replay of side effects is needed.
The synthetic project/model are explicitly labeled `supportflow-debug-replay` and
scripted regression replay. No hosted model call is made by this command.

The report is `.local/evaluations/guardrail-trace-replay.json`. Phoenix's project
API confirmed ingestion after export. Also check collector health/stored spans;
an exporter call alone is not proof of delivery. The live Groq benchmark separately
observed nine provider rate-limit errors; those remain execution failures rather
than being relabeled as hallucinations.

Storage incident during optional setup: pulling Ollama's large image filled C:
and Docker stopped responding. The pull was stopped and about 4.8 GiB recovered;
existing databases/volumes were not removed. Local-model inference was not measured
in that run. Use the storage preflight before optional model downloads.

Reference: [Phoenix](https://github.com/Arize-ai/phoenix). No hosted tracing service
or second agent is required.

## Real-model validation

The `supportflow-live-validation` project additionally contains a real GPT-OSS 20B
policy-answer turn with two model spans and one `find_policy` span under the turn
root. Phoenix's span API verified reported token usage plus actual hybrid-retrieved
policy chunks, source versions, citations and approved passage text. It used a
fictional customer and a general shipping-policy question, with in-memory checkpoints
and no business action. Normal API tracing is enabled locally; restart the API to
load its settings. The development configuration includes approved-policy passage
text, while prompts, customer tool arguments and generated answers remain omitted.
