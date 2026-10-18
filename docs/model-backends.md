# Swappable Groq, Ollama and vLLM backends

One factory, `app/agents/models.py`, supplies the same agent used by text, voice and
evaluations. Switching providers does not change tools, policies or permissions.
There is no silent cloud fallback. Optional adapters are installed with:

```powershell
pip install -e '.[dev,models]'
```

## Configuration

| Provider | Settings | Integration |
| --- | --- | --- |
| Groq (default) | `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b` | ChatGroq |
| Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen2.5:3b` | ChatOllama |
| vLLM | `LLM_PROVIDER=vllm`, `VLLM_BASE_URL=http://127.0.0.1:8001/v1`, `VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct`, `VLLM_API_KEY` | ChatOpenAI against the compatible endpoint |

Restart the API after changing `.env`. Local backends do not require a Groq key.
Temperature is zero; `MODEL_TIMEOUT` defaults to 60 seconds. Groq/vLLM disable
implicit SDK retries so rate limits/latency remain visible. Ollama uses an 8192-token
context and a 1024-token output cap. Use models that support native tool calls;
plain text that looks like a function call is not enough.

## Local Ollama setup and resource check

Run this **before downloading images**, selecting the filesystem that actually
holds Docker's data disk:

```powershell
python -m scripts.check_local_resources --path C:\ --required-gib 20
```

The script exits with code 2 when filesystem headroom is insufficient. Check Docker
VM disk/RAM limits too; a passed filesystem check is not a universal model sizing
guarantee. The image, unpacked layers and model weights can consume many GB.

After adequate storage is available:

```powershell
docker compose -f docker-compose.yml -f docker-compose.models.yml --profile local-models up -d ollama
docker compose -f docker-compose.yml -f docker-compose.models.yml exec ollama ollama pull qwen2.5:3b
```

Models persist in `ollama_data`; the API is bound to loopback. The profile prevents
an ordinary untargeted Compose startup from pulling the model service accidentally.
No GPU is requested by the supplied profile. CPU speed and RAM may still be limiting.
For a containerized SupportFlow API on the shared network use
`OLLAMA_BASE_URL=http://ollama:11434`.

**This machine's actual inference validation was blocked by storage:** the optional
image pull filled C: and was stopped; space was recovered and existing services
restored. No Ollama inference score is claimed. Both actual client adapters were
tested with isolated HTTP protocol fixtures, including native tool calls and token
usage. Those tests establish client compatibility, not downloaded-model quality.

## vLLM deployment boundary

Run the model server in a suitable Linux/WSL/container environment with compatible
hardware. Configure automatic tool choice and the correct model-specific parser.
For example, Qwen2.5 normally uses the Hermes tool parser:

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --host 127.0.0.1 --port 8001 --enable-auto-tool-choice --tool-call-parser hermes
```

Check the [official tool-calling guide](https://docs.vllm.ai/en/latest/features/tool_calling/)
for the installed server/model version. SupportFlow does not install or start a
GPU vLLM server in its Windows environment. Serving/API keys, TLS and network access
remain server deployment responsibilities. The application adapter expects `/v1`.

## Reproducible comparison

```powershell
python -m scripts.evaluate --mode agent --live --provider groq
python -m scripts.evaluate --mode agent --live --provider ollama --model qwen2.5:3b
python -m scripts.evaluate --mode agent --live --provider vllm --model Qwen/Qwen2.5-7B-Instruct
python -m scripts.compare_models PATH_TO_REPORT_ONE.json PATH_TO_REPORT_TWO.json --output docs/model-comparison.md
```

`--live` permits inference, including hosted calls where selected. CLI provider/
model overrides affect that process only. `--delay-seconds 30` can pace scenarios;
it does not retry failed actions or guarantee avoidance of token/request quotas.
Use repeated `--scenario` flags for a labeled subset. A subset is not a full score.

Comparison requires identical dataset fingerprint, prompt, scorer, selected IDs
and guardrail version. It reports overall pass rate, raw completed-only pass rate,
latency, reported token usage/cost scope and paired claim rates. Errors/timeouts
remain failures. Local API fee is zero by convention, excluding hardware and power;
hosted cost stays unknown unless both explicit per-million-token prices are supplied:

```powershell
python -m scripts.compare_models REPORT_ONE.json REPORT_TWO.json --input-usd-per-million YOUR_INPUT_RATE --output-usd-per-million YOUR_OUTPUT_RATE
```

Such costs are estimates from available reported usage, not billing receipts;
failed calls or missing usage can make them incomplete. Do not insert guessed
prices or fabricate a result for an unrun model. Record hardware, cold/warm protocol,
quantization, server limits and repeated runs for a serious model-selection study.

The initial full Groq run completed four of thirteen scenarios successfully and
hit rate-limit errors on nine. That is a 4/13 overall result with 4/4 completed
behavioral passes, not proof of 30.8% intrinsic model accuracy. A separately labeled
three-scenario hosted-model comparison is published with its precise scope.
