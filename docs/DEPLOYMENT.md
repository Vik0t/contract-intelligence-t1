# T1 Contract Intelligence Documentation

Welcome to the **T1 Contract Intelligence** — a powerful service designed to extract important information from contracts and legal documents using AI.

## Prerequisites

- **Python 3.12+** - For the backend
- **Node.js 18+** - For the frontend
- **PostgreSQL** - Database
- **uv** (recommended) or pip - Python package manager

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

Create a `.env` file in the root directory and set PostgreSQL connection string:

```env
# Database
# Skip ":password" part if no password
DATABASE_URL=postgresql://username:password@localhost:5432/contract_intelligence
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
uv pip install -r requirements.txt
```

### 4. Start the backend server
```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at: `http://localhost:8000`

### 5. Verify backend is running
```bash
curl http://localhost:8000/ping
# Expected response: "pong!"
```

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