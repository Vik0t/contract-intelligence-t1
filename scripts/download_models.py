"""Explicit, separate download step. No contracts are sent to any service."""

import json
from pathlib import Path

from huggingface_hub import snapshot_download
from scripts.check_runtime import model_specs, verify_weights


def main() -> None:
    for model, revision in model_specs():
        folder = Path(snapshot_download(
            model, revision=revision,
            allow_patterns=["*.json", "*.safetensors", "*.bin", "*.model", "*.tiktoken", "*.txt", "*.jinja", "*.py", "LICENSE*", "README.md"],
        ))
        verify_weights(folder)
        print(json.dumps({"model": model, "resolved_revision": folder.name}), flush=True)


if __name__ == "__main__":
    main()
