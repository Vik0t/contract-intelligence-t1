"""Fail early on missing weights/GPU rather than failing the first user's job."""

import json
import os
import sys

from scripts.check_runtime import check_runtime


def main() -> None:
    backends = {os.getenv(name, "local") for name in ("EXTRACTION_BACKEND", "SUMMARY_BACKEND", "RISK_BACKEND")}
    local = backends == {"local"}
    if local:
        if os.getenv("ML_ALLOW_EXTERNAL", "false").lower() != "false":
            raise RuntimeError("Локальный серверный профиль требует ML_ALLOW_EXTERNAL=false")
    elif backends == {"api"}:
        if os.getenv("ML_ALLOW_EXTERNAL", "false").lower() != "true":
            raise RuntimeError("API-профиль требует явного ML_ALLOW_EXTERNAL=true")
        if not all(os.getenv(name) for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "EXTRACTION_API_MODEL", "SUMMARY_MODEL_NAME", "RISK_MODEL_NAME")):
            raise RuntimeError("Для API-профиля не заданы адрес, ключ или имена моделей")
    else:
        raise RuntimeError("Используйте согласованный local или api серверный профиль")
    print(json.dumps(check_runtime(require_gpu=local, require_models=local), ensure_ascii=False), flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"])


if __name__ == "__main__":
    main()
