# T1 Contract Intelligence Documentation

Welcome to the **T1 Contract Intelligence** — a powerful service designed to extract important information from contracts and legal documents using AI.

## Prerequisites

- **Python 3.12–3.13** - For the backend and reproducible ML wheels
- **Node.js 18+** - For the frontend
- **PostgreSQL** - Database for multi-user deployments; SQLite is suitable for local development
- **uv** - Python package manager

## Database Setup

### 1. Start PostgreSQL

**macOS (using Homebrew):**
```bash
brew services start postgresql
```

**Linux (Ubuntu/Debian):**
```bash
sudo service postgresql start
```

**Windows:**
```bash
# Start PostgreSQL service from Services or use pg_ctl
pg_ctl -D "C:\Program Files\PostgreSQL\data" start
```

### 2. Create Database

```bash
# Connect to PostgreSQL
psql -d postgres

# Create database
CREATE DATABASE contract_intelligence;

# Exit psql
\q
```

### 3. Configure Database Connection

For local development, use the SQLite configuration from `.env.example`:

```bash
cp .env.example .env
```

This uses `sqlite:///documents.db` and does not require PostgreSQL. For a
multi-user deployment, replace it with a connection string containing an
actual PostgreSQL role and database name:

```env
# Replace every placeholder with real values; do not use "username" literally.
# Skip ":password" only when the PostgreSQL role has no password.
DATABASE_URL=postgresql://<actual_user>:<password>@localhost:5432/contract_intelligence
```

## Backend Setup

### 1. Navigate to root directory
```bash
cd contract-intelligence-t1
```

### 2. Create virtual environment (optional but recommended)

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies
```bash
uv sync
```

### 4. Start the backend server
```bash
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

The backend will be available at: `http://localhost:8000`

### 5. Verify backend is running
```bash
curl http://localhost:8000/ping
# Expected response: "pong!"
```

## Production checklist

- Copy `.env.example` to `.env` and set `DATABASE_URL`, `DOCUMENT_STORAGE_DIR`, and exact `CORS_ORIGINS`.
- Keep uploaded files in private durable storage; do not expose `DOCUMENT_STORAGE_DIR` through the frontend web server.
- Run one GPU worker per GPU. The built-in job runner is durable for a single local process; use Redis/RQ/Celery before scaling to multiple backend processes.
- Windows uses the explicit PyTorch CUDA 13.0 index configured in `pyproject.toml`; Apple Silicon macOS uses the MLX profile and CPU/Metal-compatible PyTorch wheels.
- CUDA uses BF16 for NuExtract by default; set `CONTRACT_MODEL_QUANTIZATION=8bit` only when BF16 is unavailable or memory-constrained.
- Use `uv sync` so platform markers and the lockfile select the correct ML runtime.
- Rotate any API key that was ever committed or shared outside the secret manager. The local NuExtract pipeline does not require `OPENROUTER_API_KEY`.
- Run `uv run python -m pytest -q` and `npm run build` before release.

## Frontend Setup

### 1. Navigate to frontend directory
```bash
cd frontend
```

### 2. Install dependencies
```bash
npm install
```

### 3. Start the frontend development server
```bash
npm run dev
```

The frontend will be available at: `http://localhost:5173` (or the port shown in terminal)

## Running Both Services

**Terminal 1 - Backend:**
```bash
# In root directory
uvicorn backend.app:app --reload
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

---

> 🚀 **T1 Contract Intelligence**
