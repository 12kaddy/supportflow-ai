# Evaluation

The default versioned dataset in `data/evaluations/support_v2.json` contains ten policy
scenarios and thirteen agent scenarios. Run deterministic policy checks offline:

```powershell
python -m scripts.evaluate
```

Reports are saved under `.local/evaluations/` with per-scenario results, overall
and per-check pass rates, latency, and a dataset fingerprint. The CLI exits with
status 1 when a scenario fails. CI runs policy evaluation and saves the report
as a workflow artifact. A perfect policy score validates these rule scenarios;
it does not measure LLM quality or production resolution success.

To evaluate the configured Groq model explicitly:

```powershell
python -m scripts.evaluate --mode agent --live
```

This makes hosted model calls using your configured account. It does not connect
to PostgreSQL, create real cases, or execute refunds. It runs the production
system prompt against isolated in-memory tool fixtures, with a fresh graph for
each scenario. Each scenario has a 45-second timeout and a bounded graph step
count. Calls run sequentially, with progress printed per scenario.

Agent reports include final responses, tool names and arguments, tool errors,
available token usage, model name, prompt fingerprint, and latency. Scores check
tool selection, argument accuracy, required response facts, forbidden claims,
and nonempty answers. Scenarios include missing order IDs, ownership failures,
case reuse, missing evidence, approved versus executed states, simulated payments,
and unsupported notification promises. They use fictional customer data only.

Response checks use regular-expression rubrics. They can miss paraphrases or
flag a negated/quoted claim and require human inspection; they are not a semantic
hallucination detector. Fixtures test model behavior, not persistence, retrieval
quality, or concurrency. Real tool authorization and transactions are tested by
the integration suite. No cost estimate is made; token usage is recorded only
when the provider supplies it. Exception reports include error types without
provider exception text. Use `--dataset` and `--output-dir` for custom runs.

Notification claims must match per-case tool results. Evaluation fixtures keep
notifications disabled; real cases may use verified-account status emails.

Rubric v2 normalizes Unicode hyphens and whitespace when checking response text
(tool arguments must still match exactly), accepts an existing-case lookup for a
repeat report, and recognizes "unable to locate" as an order lookup denial.
It also flags invented currency, broader notification promises, and a proposal
reason incorrectly labeled as a rejection reason. The v1 dataset remains available
for reference; scoring changes mean old and new scores are not directly comparable.

Rescore a saved agent report without new hosted calls:

```powershell
python -m scripts.rescore .local/evaluations/your-agent-report.json
```

Rescoring writes a separate report, retaining the original inference prompt
fingerprint, model responses, and latencies. It records the source report fingerprint
and new scorer version. It does not demonstrate that a changed prompt improves
future responses; run the live benchmark again to measure that.

Rubric v3 accepts a correctly labeled "Proposal reason" or "Investigation reason"
on a rejected case, while continuing to flag an unlabeled rejection reason inferred
from that proposal. Reports separate execution errors (such as provider rate limits)
from completed behavioral failures. Overall pass rate still includes errors;
`completed_pass_rate` and individual check rates include completed scenarios only.

After a provider rate limit clears, rerun just the affected scenario:

```powershell
python -m scripts.evaluate --mode agent --live --scenario unknown-order-owner
```

Repeat `--scenario` to select several IDs. Each run writes a separate report and
does not alter or merge previous results. A selected run measures only its listed
scenarios, not the full benchmark. The rescore command currently requires a full
report matching every scenario in the target benchmark.
