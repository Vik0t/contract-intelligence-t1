# Evaluation metadata

Complete structured annotations are distributed separately from the documents:
[meta.zip](https://drive.google.com/file/d/1aSvJMbpT9Umq2omGPZoRIPBtFmZN3lZz/view).
It contains 50 numbered JSON files, `meta/1.json` … `meta/50.json`, describing
50 contracts and all 125 PDF/DOCX/PNG variants. The embedded `dataset/meta.json`
is an older 27-contract annotation set, not the full gold source.

Restore with `python tools/make_dataset.py --labels-only` from the repository
root. For a manually downloaded private archive, add `--meta-archive /path/to/meta.zip`.
The installer preserves existing differing files. No dataset credentials are
embedded in the downloader.

The numbered JSON files contain contract parties and identifiers and are ignored
by Git. Keep the source archives in controlled storage; `schema.json` describes
the label structure without document contents. Downloaded labels stay unchanged.
Five source-checked corrections can be reproduced into a separate directory via
`python -m scripts.review_dataset_labels --source meta --output tmp/meta-reviewed`.
The correction manifest explains every edit; the source fingerprint must match.

Verified upstream archive SHA-256:
`74e29042e8aa80e5c60b15fce420d268c15ee3f239564d81317e8b3634469257`.
Verified raw numbered-label fingerprint:
`81362d906af75335fcf1e89d60ec05240b897a35123022555a2677cefa87dc56`.

[Evaluation commands and provenance](../evals/README.md).
