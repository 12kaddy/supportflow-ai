# Recorded model comparison

API fees exclude local hardware/electricity. Unknown hosted cost is not zero.

| Provider / model | Pass rate | Raw completed pass rate | Mean latency | API cost | Claim violations before → after |
| --- | --- | --- | --- | --- | --- |
| groq / openai/gpt-oss-120b | 2/3 (66.7%) | 66.7% | 2.01 s | unknown | 33.3% → 0.0% |
| groq / openai/gpt-oss-20b | 3/3 (100.0%) | 66.7% | 1.32 s | unknown | 33.3% → 0.0% |

Results use fixture tools, small datasets and heuristic scoring; failures/timeouts remain in overall pass rates.
Raw pass rate and claim rates use completed scenarios only. No result is supplied for unrun models.

## Scope and provenance

Measured 18 October 2026 with 30-second pacing between scenarios. This is a
**three-scenario subset**, not the full thirteen-case benchmark: missing-delivery
report, approved-but-not-executed status, and approval injection. Both use the same
dataset/prompt/scorer/guardrail fingerprints and fixture tools. Latency is per-case
execution time; the deliberate between-case wait is excluded.

The 120B failure was an extra read-only lookup on the injection scenario, not an
executed refund. Production input screening rejects that attack before model/tool
invocation; this evaluation intentionally measures raw model behavior before the
output verifier. The 20B raw score improved from 2/3 to 3/3 after output correction.
One run and three cases do not establish that the smaller model is generally better.

Source reports remain ignored local artifacts:

- `.local/evaluations/comparison/agent-20261018T160558Z-c7d8c87b.json` (120B).
- `.local/evaluations/comparison/agent-20261018T160948Z-282e18b0.json` (20B).

An earlier full 120B attempt had 4 completed passes and 9 provider rate-limit errors.
An attempted Llama model was unavailable to the configured account (NotFoundError)
and is excluded from this quality table. Its failure report is preserved locally.
Ollama model inference was not run because its image exhausted C: during extraction;
the download was stopped and existing Docker services restored. vLLM was tested
through its client protocol, not a real GPU server. No local inference score is invented.

## Token-cost equivalent (not actual billing)

The reports contain 6,072 input / 1,224 output tokens for 120B and 4,945 input /
989 output tokens for 20B. At published **uncached** list prices checked on
18 October 2026, their three-case token-cost equivalents are:

| Model | USD per million input/output tokens | Three-case list-price equivalent |
| --- | --- | --- |
| GPT-OSS 120B | 0.15 / 0.60 | USD 0.0016452 |
| GPT-OSS 20B | 0.075 / 0.30 | USD 0.000667575 |

Formula: `(input_tokens * input_rate + output_tokens * output_rate) / 1,000,000`.
Rates come from the official [120B model page](https://console.groq.com/docs/model/openai/gpt-oss-120b)
and [20B model page](https://console.groq.com/docs/model/openai/gpt-oss-20b).
These are price-equivalent estimates, not charges to the user's free-tier account
or billing receipts. Caching, service tiers, missing usage and pricing changes can
change actual cost. The main table leaves actual billed API cost unknown.
