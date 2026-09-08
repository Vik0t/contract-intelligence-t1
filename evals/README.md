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
