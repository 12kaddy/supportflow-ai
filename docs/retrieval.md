# Policy retrieval

Policy search combines BM25 keyword ranking with Chroma vector candidates using
reciprocal rank fusion. This is rank fusion, not a neural reranker. Policies are
split into deterministic chunks of up to 900 characters. Each result includes
its filename, manifest version, document SHA-256, chunk ID, ranking score, retrieval
methods, and a citation such as `shipping_policy.md@shipping-v1#<chunk-id>`.
Scores are relative rankings, not confidence or authorization decisions.

Approved filenames and versions are declared in `data/knowledge_base/manifest.json`.
Add every policy file there and bump its version when changing policy meaning.
Content changes also change chunk IDs, preventing stale vector chunks from being
returned as current evidence. Backend refund authorization remains deterministic
and independent of retrieval; editing a policy file does not change those rules.

After updating or installing this retrieval implementation:

```powershell
python -m scripts.ingest
```

The new `support_policy_chunks_v1` Chroma collection uses cosine distance. Ingestion
upserts current chunks, then removes stale chunks from that collection. The legacy
`support_policies` collection is left intact. Source paths resolve from the project
location, independent of the shell's current directory. No SQL migration is needed.

If embeddings are unavailable or the vector collection is empty, keyword retrieval
still works and results report `vector_status`. Current vector matches beyond
cosine distance 0.65 are excluded; that initial threshold is not calibrated on a
large corpus. Responses are instructed to cite returned passages and acknowledge
missing evidence. This does not provide automated semantic entailment verification.

Run the eight-query source-ranking benchmark:

```powershell
python -m scripts.evaluate_retrieval
python -m scripts.evaluate_retrieval --vectors
```

The default run is offline keyword-only and runs in CI. `--vectors` uses the local
embedding model and may download its files; ingest first. Reports in
`.local/evaluations/` include hit@1, recall@3, reciprocal rank, and vector availability.
A hybrid run can fall back to keywords: inspect `vector_status` before interpreting
its score. The small benchmark is a regression check, not evidence of broad semantic
retrieval quality. Content-free `policy_retrieval_completed` telemetry records
candidate counts and vector availability without logging queries or passages.
