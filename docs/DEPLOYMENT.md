# T1 Contract Intelligence Documentation

## Полностью локальное развёртывание НГУ через Docker

Подготовлен отдельный Linux/CUDA-профиль для одной NVIDIA GPU: H100 или RTX 5090.
Docker Engine и Compose с поддержкой `gpus` (Compose 2.30+) должны быть установлены
вместе с NVIDIA Container Toolkit. Проверьте доступность GPU внутри контейнеров.
Образ использует CUDA 12.8 и PyTorch 2.7.1, в отличие от native-профиля `uv` ниже.
На сервере нужен совместимый с CUDA 12.8 драйвер NVIDIA; установка драйвера не входит в образ.

```bash
cp .env.server.example .env.server
openssl rand -hex 24
# Запишите полученный пароль в POSTGRES_PASSWORD файла .env.server.
docker compose --env-file .env.server build
docker compose --env-file .env.server --profile setup run --rm model-download
docker compose --env-file .env.server --profile validation run --rm ml-check
docker compose --env-file .env.server up -d
```

Интерфейс: `http://127.0.0.1:8080`. Для доступа из сети задайте `BIND_ADDRESS`
и используйте университетский reverse proxy с HTTPS. Адрес интерфейса внесите в
`CORS_ORIGINS`. API и PostgreSQL не публикуют отдельные порты хоста.

Во время `model-download` скачиваются только веса и конфигурации моделей,
договоры не передаются. После загрузки runtime работает с `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1` и `ML_ALLOW_EXTERNAL=false`. Backend и БД находятся
в сети Docker с `internal: true`; у backend нет маршрута в интернет.
Публичный HF Space, DeepCode и облачный fallback в этом профиле не используются.

Модели по умолчанию: `numind/NuExtract3` для полей, `Qwen/Qwen3-8B` для
сводки и предварительного поиска рисков. Обе выполняются внутри backend.
NuExtract3 — специализированная модель на основе Qwen3.5-4B; произвольная
chat-модель не является прямой заменой её extraction-шаблона.
Источники: [NuExtract3](https://huggingface.co/numind/NuExtract3),
[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B).

Веса сохраняются в volume `models`, документы — `documents`, PostgreSQL —
`database`, результаты проверки — `reports`. Не выполняйте `down -v`, если эти
данные нужны. Для резервного копирования остановите приём новых документов,
выполните `pg_dump` и сохраните volume документов; одно без другого не восстанавливает продукт.
`.env.server` и загруженные документы исключены из Git и Docker build context.

После загрузки моделей команда печатает `resolved_revision`. Для воспроизводимого
развёртывания внесите эти SHA в `CONTRACT_MODEL_REVISION` и
`SUMMARY_LOCAL_MODEL_REVISION`, затем повторите проверку. Первичная загрузка
моделей без закреплённых ревизий намеренно использует текущий `main`.
Артефакты Docker для выпуска следует собрать один раз и перенести в реестр НГУ.

На RTX 5090 оставьте `ML_KEEP_MODELS_LOADED=false`: модель извлечения выгружается
перед анализом, а аналитическая модель — перед следующим извлечением.
На H100 после измерений можно включить удержание моделей в памяти.
`Qwen/Qwen3-32B` — кандидат для сравнительной проверки на H100: измените
`SUMMARY_LOCAL_MODEL_NAME`, очистите прежнюю ревизию этой модели и повторите
`model-download` и `ml-check`. Повышение качества не предполагается без измерений.

Проверка реальных моделей сохраняет `/reports/ml-check.json`, завершает работу
с ненулевым кодом при несовпадении полей, сбое парсинга или пропуске контрольных
рисков. Просмотр отчёта:

```bash
docker compose --env-file .env.server --profile validation run --rm --no-deps \
  --entrypoint python ml-check -c 'from pathlib import Path; print(Path("/reports/ml-check.json").read_text())'
docker compose --env-file .env.server logs -f backend
curl http://127.0.0.1:8080/api/health/ready
```

Не запускайте `ml-check` одновременно с рабочим backend на той же GPU:
проверка создаёт отдельный процесс с собственными моделями.
Успешный healthcheck означает доступность API/БД после проверки GPU и файлов
весов при старте. Он не заменяет реальную генерацию в `ml-check` и оценку на
отложенных размеченных договорах. Подробности — [ML-аудит](ML_AUDIT.md).

Контейнер пока рассчитан на один процесс API (`--workers 1`) и одну очередь
обработки. Для нескольких GPU/процессов нужна отдельная распределённая очередь.
Документы для полноценного benchmark и доступ к серверу НГУ в репозитории отсутствуют.

## Вариант с DeepCode API без GPU

Этот профиль явно разрешает отправку текста договора в настроенный DeepCode.
Он не используется локальным профилем автоматически.

```bash
cp .env.api.example .env.api
# Заполните POSTGRES_PASSWORD, OPENAI_BASE_URL, OPENAI_API_KEY.
# Укажите точный alias модели во всех трёх *_MODEL* переменных.
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml build
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml \
  --profile validation run --rm ml-check
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml up -d
```

`SERVER_ENV_FILE=.env.api` в шаблоне выбирает правильный env-файл для сервисов.
Образ собирается с CPU PyTorch, NVIDIA GPU и загрузка весов не требуются.
Для `!reset`/`!override` в override-файле нужна Compose 2.30+.

В `.env.api.example` указан подтверждённый ID `qwen3.8-flash-next`.
DeepCode различает регистр: прежнее `Qwen3.8-Flash-Next` давало `400 Model not found`.
Клиент сопоставляет имя с `/models` без учёта регистра и отправляет точный ID
провайдера; он не подменяет запрос другой моделью. Benchmark проверяет API
до загрузки локальной модели и сохраняет безопасный текст ошибок в отчёт.
Для Qwen через DeepCode по умолчанию передаётся
`chat_template_kwargs.enable_thinking=false`: внутреннее рассуждение иначе
может исчерпать лимит ответа и оставить пустой `content`.
Для отдельного эксперимента доступно `DEEPCODE_ENABLE_THINKING=true`;
benchmark фиксирует non-thinking режим для обеих моделей.
TLS-проверка не отключается, в образ нужно добавить доверенный
CA университета, если endpoint использует внутренний центр сертификации.
Тайм-аут handshake следует устранять доступностью сети/VPN/endpoint, а не заменой модели.

Сравнение извлечения на синтетических положительных/отрицательных/длинных
примерах: `python -m scripts.benchmark_models --api-model qwen3.8-flash-next --backends local api --repeats 3 --insights`.
Первый локальный запрос включает загрузку модели; warm latency считается отдельно.
Для решения о замене NuExtract нужен отложенный набор реальных договоров.

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
