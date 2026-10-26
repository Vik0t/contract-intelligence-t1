# Offline evaluation

Completed comparison: [125-file results, 27 October 2026](RESULTS_2026-10-27.md).

## Full corpus comparison

`scripts.benchmark_dataset` compares local NuExtract3 with the configured DeepCode
model using identical cached text and DocumentIR. The current corpus has 50 PDF,
50 DOCX and 25 PNG files; legacy `dataset/meta.json` labels cover 27 contract IDs
(58 file variants), not the entire corpus. No gold summaries or risk annotations
are available. Insight checks establish execution/citation grounding, not legal
accuracy. Reports and caches contain document data and stay under ignored `tmp/`.

```bash
python -m scripts.benchmark_dataset prepare --output tmp/full-comparison-2026-10-26
python -m scripts.benchmark_dataset run --backend local --output tmp/full-comparison-2026-10-26
python -m scripts.benchmark_dataset run --backend api --allow-external-data --insights --workers 2 --output tmp/full-comparison-2026-10-26
python -m scripts.benchmark_dataset compare --output tmp/full-comparison-2026-10-26
```

Preparation reads every format, converts DOCX through LibreOffice and performs
OCR where needed. Exact duplicate model inputs reuse a successful prediction;
reuse is recorded and excluded from inference timing. API/local runs may execute
in separate processes after preparation. Use `--resume` after interruption;
changing extraction/parsing/scoring code requires a fresh prepared run. Do not
tune model prompts during a comparison. Evaluation counts failed labeled files
as failures, also reporting accuracy conditional on successful extraction.
Company names and INNs are matched as pairs. Paired confidence intervals resample
contract IDs rather than treating format variants as independent documents.

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
