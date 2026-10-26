"""One generation at a time on a single GPU, including manual insight refreshes."""

import gc
import os
import threading

MODEL_LOCK = threading.RLock()


def external_inference_allowed() -> bool:
    return os.getenv("ML_ALLOW_EXTERNAL", "false").strip().lower() in {"true", "1", "yes"}


def keep_models_loaded() -> bool:
    return os.getenv("ML_KEEP_MODELS_LOADED", "false").strip().lower() in {"true", "1", "yes"}


def release_device_memory() -> None:
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

