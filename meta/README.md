# Evaluation metadata

The numbered JSON files contain document-level gold labels used by the offline benchmark. They are intentionally kept outside the regular Git source set because they may contain contract parties and identifiers.

Keep a versioned copy in DVC, private object storage, or another controlled artifact store. `schema.json` documents the label contract without containing document data.
