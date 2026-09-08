# T1 Contract Intelligence

Welcome to the **T1 Contract Intelligence** — a powerful service designed to extract important information from contracts and legal documents using AI.

## Documentation

- **[API Documentation](docs/API.md)** - Endpoints and usage
- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production setup
- **[Operations Guide](docs/OPERATIONS.md)** - Jobs, limits, tests, and recovery

---

## Quick start

```powershell
Copy-Item .env.example .env
uv sync
uv run uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

The frontend runs separately from `frontend/` with `npm install` and `npm run dev`.

The local pipeline uses the NuExtract model and does not require an OpenRouter key.

> 🚀 **T1 Contract Intelligence**
