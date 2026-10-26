"""Validate GPU, OCR and cached weights without downloading or loading a model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

MODEL_FILES = ["*.json", "*.safetensors", "*.bin", "*.model", "*.tiktoken", "*.txt", "*.jinja", "*.py", "LICENSE*", "README.md"]


def model_specs() -> list[tuple[str, str | None]]:
    return [
        (os.getenv("CONTRACT_MODEL_ID", "numind/NuExtract3"), os.getenv("CONTRACT_MODEL_REVISION") or None),
        (os.getenv("SUMMARY_LOCAL_MODEL_NAME", "Qwen/Qwen3-8B"), os.getenv("SUMMARY_LOCAL_MODEL_REVISION") or None),
    ]


def verify_weights(folder: Path) -> None:
    if not (folder / "config.json").is_file():
        raise RuntimeError(f"Нет config.json: {folder.name}")
    indices = list(folder.glob("*.index.json"))
    weight_files = set()
    for index in indices:
        weight_files.update(json.loads(index.read_text())["weight_map"].values())
    if not weight_files:
        weight_files = {item.name for item in folder.glob("*.safetensors")} or {item.name for item in folder.glob("pytorch_model*.bin")}
    if not weight_files or any(not (folder / name).is_file() for name in weight_files):
        raise RuntimeError(f"Веса модели неполные: {folder.name}; повторите model-download")


def check_runtime(*, require_gpu: bool = True, require_models: bool = True) -> dict:
    import torch
    from huggingface_hub import snapshot_download

    if require_gpu and not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU недоступна. Проверьте NVIDIA Container Toolkit и docker --gpus all")
    gpu = None
    if torch.cuda.is_available():
        capability = torch.cuda.get_device_capability()
        arch = f"sm_{capability[0]}{capability[1]}"
        if require_gpu and arch not in torch.cuda.get_arch_list():
            raise RuntimeError(f"PyTorch не содержит поддержку {arch}; установите CUDA-сборку для этой GPU")
        gpu = {"name": torch.cuda.get_device_name(), "vram_gib": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1), "architecture": arch}
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise RuntimeError("LibreOffice не установлен: нельзя сверить страницы DOCX с оригиналом")
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError("Tesseract не установлен")
    languages = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True, check=True, timeout=15).stdout
    if not {"rus", "eng"}.issubset(set(languages.split())):
        raise RuntimeError("Для OCR нужны языки Tesseract rus и eng")
    models = []
    if require_models:
        for model, revision in model_specs():
            folder = Path(snapshot_download(model, revision=revision, local_files_only=True, allow_patterns=MODEL_FILES))
            verify_weights(folder)
            models.append({"model": model, "revision": folder.name})
    return {"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": gpu, "models": models, "ocr": "rus+eng", "docx": "LibreOffice"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check_runtime(require_gpu=not args.allow_cpu, require_models=not args.skip_models), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
