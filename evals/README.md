# Offline evaluation

The numbered benchmark scripts currently live under `tests/` for compatibility
with the existing workflow:

- `evaluate_50_run.py` runs the 50-document benchmark;
- `analyze_50_metrics.py` summarizes the benchmark;
- `analyze_50_new_meta.py` compares results with the current labels.

They are intentionally kept separate from the regular `pytest` suite by their
names and are not part of the product runtime. A future ML pass can move them
here together with versioned evaluation configuration and private label
artifacts.

## Hugging Face Space experiment

`benchmark_hf_space.py` calls the public `numind/NuExtract3` Gradio Space with
the current project template, measures the end-to-end request time, parses the
JSON response, and scores it against `meta/<id>.json`.

First inspect the remote API without sending project data:

```powershell
uv run python evals/benchmark_hf_space.py --view-api
```

The benchmark refuses to send project documents by default. Review the privacy
implications before explicitly enabling the request:

```powershell
uv run python evals/benchmark_hf_space.py `
  --document-id 2 `
  --prompt-mode compact `
  --context-mode retrieved `
  --context-chars 3000 `
  --allow-external-data
```

The public Space currently reserves a fixed 15k-token output budget inside an
18k-token context window. The default full/production prompt can therefore
fail on long contracts with an HTTP 400 context-length error. The compact
retrieval mode is an explicit experiment and must be evaluated against the
full local pipeline before being used as a product default.

The public Space may sleep, queue requests, rate-limit callers, or change its
endpoint. Do not use it for confidential production documents. The benchmark
stores the parsed result and raw remote response in `evals/` for local review.
