# Offline evaluation

Corrected full-label comparison: [125 files / 50 labeled contracts, 27 October 2026](RESULTS_2026-10-27.md).

Field-level causes and source-backed fixes: [error analysis, 27 October 2026](ERROR_ANALYSIS_2026-10-27.md).

## Full corpus comparison

`scripts.benchmark_dataset` compares local NuExtract3 with the configured DeepCode
model using identical cached text and DocumentIR. The current corpus has 50 PDF,
50 DOCX and 25 PNG files. The separate `meta.zip` provides structured gold for all 50 contract IDs; the older embedded `dataset/meta.json` covers only 27 IDs
(58 file variants), not the entire corpus. No gold summaries or risk annotations
are available. Insight checks establish execution/citation grounding, not legal
accuracy. Reports and caches contain document data and stay under ignored `tmp/`.

```bash
python -m scripts.benchmark_dataset prepare --output tmp/full-comparison-new-run
python -m scripts.benchmark_dataset run --backend local --output tmp/full-comparison-new-run
python -m scripts.benchmark_dataset run --backend api --allow-external-data --insights --workers 2 --output tmp/full-comparison-new-run
python -m scripts.benchmark_dataset compare --output tmp/full-comparison-new-run
```

Preparation reads every format and performs OCR where needed. DOCX uses the
native parser, matching the application; `--docx-parser rendered-pdf` explicitly
selects the historical LibreOffice route. Deployment profiles with
`DOCX_USE_RENDERED_PAGES=true` require that option when measuring the deployed
profile; a native comparison corresponds to `DOCX_USE_RENDERED_PAGES=false`. Reuse requires equal text, source
format and source-file hash: equal text across PDF/DOCX is insufficient because
party identity resolution also reads source layout. Reuse is recorded and
excluded from inference timing. API/local runs may execute
in separate processes after preparation. Use `--resume` after interruption;
changing extraction/parsing/scoring code requires a fresh prepared run. Do not
tune model prompts during a comparison. Evaluation counts failed labeled files
as failures, also reporting accuracy conditional on successful extraction.
Company names and INNs are matched as pairs. Paired confidence intervals resample
contract IDs rather than treating format variants as independent documents.

`tests/evaluate_50_run.py` remains a single-format local diagnostic. It also
uses structured `--labels meta` by default and rejects resumes under a different
annotation fingerprint. Use `scripts.benchmark_dataset` for the complete
multi-format comparison and offline rescoring.

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


## Restore the complete labels and rescore saved model outputs

The document archive and the annotation archive are separate. Restore both with:

```bash
python tools/make_dataset.py
# Or only labels, preserving existing documents:
python tools/make_dataset.py --labels-only
# A privately downloaded archive can be supplied without anonymous Drive access:
python tools/make_dataset.py --labels-only --meta-archive /path/to/meta.zip
```

The numbered files are installed as `meta/1.json` … `meta/50.json`, never
`meta/meta/1.json`. Existing differing labels are preserved and produce an error.
Raw labels and archives remain outside Git.

```bash
# Full upstream labels, no new model calls:
python -m scripts.benchmark_dataset rescore \
  --source-results tmp/full-comparison-2026-10-26 \
  --labels meta --output tmp/full-comparison-meta50-raw

# Optional, separately recorded source-checked annotation corrections:
python -m scripts.review_dataset_labels --source meta --output tmp/meta-reviewed
python -m scripts.benchmark_dataset rescore \
  --source-results tmp/full-comparison-2026-10-26 \
  --labels tmp/meta-reviewed --output tmp/full-comparison-meta50-reviewed
```

Fresh `prepare` defaults to structured `--labels meta`. Incomplete coverage is
rejected unless `--allow-unlabeled` is explicitly selected. To reproduce legacy
scoring, specify `--labels dataset/meta.json --allow-unlabeled`.

Rescoring preserves the original reports, input hashes and inference code hash.
It records separate annotation and evaluator hashes. Structured VAT requires
both the value and mode to match; `not_found` is not a zero rate. Party order
is matched without detaching INNs from names. PDF page agreement is reported
separately; shared gold page numbers are not applied to stitched PNGs or
LibreOffice-repaginated DOCX files.

## Missing fields and party identity

Both backends resolve full/abbreviated legal names and source-backed INN records
after chunk merging. Different named entities are never merged solely by INN.
PDF column proofs and native DOCX records retain a source hash; ambiguous links
require review.

The API backend enables one bounded repair request for missing date, signing
place, total or party data when relevant source cues exist. Source quotes and
values are checked, existing scalar values are preserved, and repair failures
leave the first-pass result available. Set `EXTRACTION_API_REPAIR_ENABLED=false`
to disable this product feature; the full benchmark explicitly enables it and
records that setting. Reported API time includes the repair.
