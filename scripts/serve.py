"""Fail early on missing weights/GPU rather than failing the first user's job."""

import json
import os
import sys

from scripts.check_runtime import check_runtime, model_specs


def runtime_requirements() -> dict[str, bool]:
    stages = {
        'EXTRACTION_BACKEND': os.getenv('EXTRACTION_BACKEND', 'local'),
        'SUMMARY_BACKEND': os.getenv('SUMMARY_BACKEND', 'local'),
        'RISK_BACKEND': os.getenv('RISK_BACKEND', 'local'),
    }
    for name, backend in stages.items():
        allowed = {'local', 'api', 'rules', 'huggingface-space'} if name == 'EXTRACTION_BACKEND' else {'local', 'api'}
        if backend not in allowed:
            raise RuntimeError(f'Недопустимое значение {name}: {backend}')
    if stages['EXTRACTION_BACKEND'] == 'rules':
        return {'require_gpu': False, 'require_models': False}
    external = any(backend in {'api', 'huggingface-space'} for backend in stages.values())
    if external and os.getenv('ML_ALLOW_EXTERNAL', 'false').strip().lower() not in {'true', '1', 'yes'}:
        raise RuntimeError('Внешние backend требуют явного ML_ALLOW_EXTERNAL=true')
    # Provider credentials and model defaults are validated by the configured clients.
    local_models = bool(model_specs())
    return {'require_gpu': local_models, 'require_models': local_models}


def main() -> None:
    from backend.config import get_settings
    from backend.delivery_profile import validate_delivery_profile
    validate_delivery_profile(get_settings())
    print(json.dumps(check_runtime(**runtime_requirements()), ensure_ascii=False), flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"])


if __name__ == "__main__":
    main()
