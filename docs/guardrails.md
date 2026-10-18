# Guardrails and evidence verification

`GUARDRAILS_ENABLED=true` is the code default. Text and voice use the shared
runtime; ownership, reviewer permissions and backend refund rules remain the
authorization boundary.

## Input

Lightweight regex rules screen common instruction overrides, secret extraction,
reviewer impersonation and approval bypass, including selected Hindi patterns.
Blocked requests receive a refusal without invoking the graph/model. This is not
a comprehensive multilingual classifier; quoted attacks can trigger false positives.

Email addresses, common Indian phone patterns, grouped Aadhaar, PAN-like IDs and
card-like digit sequences are replaced with typed placeholders before the new
message reaches inference and checkpoint storage. This does not comprehensively
detect names, addresses, spoken numbers, unusual formatting or sanitize older
stored history. It is not identity-document validation or a complete PII guarantee.

## Output and checkpoints

Only tools after the current human message supply facts. Regex audit checks cover
common affirmative payment/approval claims, explicit status mismatches, reported
minor-unit amounts and invented currency. Negation/paraphrase checks are heuristic.

For current case results, prose is rebuilt deterministically from verified fields,
even when an English regex misses a paraphrase. Templates distinguish proposal,
approval and simulation, preserve IDs, report policy/missing evidence, and avoid
inventing rejection reasons. English/Hindi/Marathi/Tamil/Telugu templates are
available; state codes remain literal. A verbatim structured tool result may pass
through as already grounded. The renderer summarizes the latest case result;
ask about multiple cases separately for complete summaries.

General responses without case facts get a safe fallback when a forbidden claim
is detected. Output PII is redacted. This is not semantic verification of every
policy sentence or a general hate/violence moderation model. No Llama Guard service
or learned safety-classifier accuracy is claimed.

Rewrites replace the existing assistant message in persisted graph state. Tools
are not replayed and no model retry is charged. A failed checkpoint repair raises
an error rather than claiming persistence succeeded. Interruption cannot undo a
customer-tool action that already committed.

## Measured regression metric

```powershell
python -m scripts.evaluate_guardrails
pytest tests/test_guardrails.py -q
```

Nine labeled handwritten responses contain six deliberately unsafe answers and
three valid controls. The observed fixture claim-violation rate was **6/9 (66.7%)
before → 0/9 after**. The rubric identified all nine labels in this set. This is a
fixture result, not 100% safety on unseen attacks/human traffic.

Live evaluation records raw and guarded scores from the **same generations**, plus
rewrite details, dataset/prompt fingerprints and paired claim rates. Input filtering
is tested separately so model injection behavior remains measurable in raw eval
fixtures. Execution errors remain failures in overall pass rate; completed-only
claim rates exclude them. Raw evaluation reports contain fictional responses/tool
arguments; inspect reports before publishing any custom dataset.
