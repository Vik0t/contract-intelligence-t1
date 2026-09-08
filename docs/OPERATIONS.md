# Operations guide

## Processing lifecycle

Document processing is durable at the database level and executed by a single local GPU worker:

`uploaded` → `processing` → `ready` → `extracting` → `extracted`

Failures use `failed` and can be retried. Queued and interrupted jobs are recovered on application startup. For a multi-process production deployment, replace the local worker with Redis/RQ, Celery, or another external queue and run one GPU worker per device.

## Upload limits

The defaults are configured through `.env`:

- `MAX_UPLOAD_SIZE_MB=50`
- `MAX_PDF_PAGES=200`
- `MAX_JOB_ATTEMPTS=3`
- `JOB_WORKER_COUNT=1`
- `JOB_STALE_AFTER_MINUTES=30`
- `CONTRACT_MODEL_QUANTIZATION=bf16` (CUDA default; set `8bit` only for compatibility)

Uploads are streamed to a temporary file, checked by file signature, and validated before being copied to permanent storage.

## Tests and checks

```powershell
uv run python -m pytest -q
cd frontend
npm run build
```

API tests use an isolated temporary database and storage directory. The full ML benchmark is intentionally separate from the regular test suite.

`pyproject.toml` and `uv.lock` are the installation source of truth. Windows resolves Torch from the explicit CUDA 13.0 index; Apple Silicon macOS resolves MLX only on `darwin/arm64` and compatible PyTorch wheels from PyPI.

On CUDA, the local NuExtract runtime uses BF16 by default because it is substantially faster on modern GPUs. If BF16 is unsupported or fails to load, the loader falls back to 8-bit automatically. The explicit `8bit` mode remains available through `CONTRACT_MODEL_QUANTIZATION=8bit`.

## Deployment requirements

Before deployment:

1. Revoke any previously exposed API keys and provide new secrets through the deployment secret manager.
2. Set `DATABASE_URL` to PostgreSQL for multi-user deployments.
3. Set `DOCUMENT_STORAGE_DIR` to durable private storage.
4. Set `CORS_ORIGINS` to the exact frontend origin.
5. Use one GPU worker per GPU until an external job queue is configured.
