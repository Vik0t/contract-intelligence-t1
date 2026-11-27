#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./compose.sh exec -T backend python - <<'PY'
import json
import os
import httpx
models = {stage: os.environ[name] for stage, name in (
    ('EXTRACTION_BACKEND', 'EXTRACTION_API_MODEL'),
    ('SUMMARY_BACKEND', 'SUMMARY_MODEL_NAME'),
    ('RISK_BACKEND', 'RISK_MODEL_NAME'),
) if os.getenv(stage, 'local') == 'api'}
if not models:
    print(json.dumps({'skipped': True, 'reason': 'No stages use backend=api'}))
    raise SystemExit(0)
base = os.environ['OPENAI_BASE_URL'].rstrip('/')
with httpx.Client(timeout=30, trust_env=False) as client:
    response = client.get(base + '/models', headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']})
    response.raise_for_status()
    available = {item['id'].casefold(): item['id'] for item in response.json()['data']}
    requested = set(models.values())
    missing = sorted(name for name in requested if name.casefold() not in available)
    if missing:
        raise SystemExit('Модели не найдены в /models: ' + ', '.join(missing))
    print(json.dumps({'api_accessible': True, 'models': sorted(available[name.casefold()] for name in requested)}, ensure_ascii=False))
PY
