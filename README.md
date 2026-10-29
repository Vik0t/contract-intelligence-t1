# T1 Contract Intelligence

Веб-приложение для извлечения ключевых реквизитов, суммаризации и поиска потенциальных рисков в договорах. Принимает PDF, DOCX и фотографии JPG/PNG, показывает результаты рядом с документом и сохраняет исправления и подтверждение оператора в базе данных.

## Содержание

- [Архитектура](#архитектура)
- [Состав системы](#состав-системы)
- [Быстрый старт](#быстрый-старт)
- [Тесты](#тесты)
- [API](#api)
- [Логирование](#логирование)
- [Сетевая конфигурация](#сетевая-конфигурация)
- [Документация по компонентам](#документация-по-компонентам)

## Архитектура

```text
Браузер оператора
      │ HTTP :8080
      ▼
frontend (React + Nginx)
      │ HTTP /api/*
      ▼
backend (FastAPI :8000)
      ├── SQL → db (PostgreSQL :5432)
      ├── файлы → /data/uploads
      └── JobManager
            ├── чтение документов: PyMuPDF, LibreOffice, Tesseract
            └── извлечение, сводка, риски: локальные модели / DeepCode
```

Документ обрабатывается в фоне. Оператор проверяет извлечённые поля по выделенным фрагментам, вносит исправления и подтверждает результат. Данные доступны для копирования и скачивания в JSON.

Извлекаются номер, дата, тип и место заключения договора, срок, названия и ИНН сторон, сумма, валюта и НДС. Для значений сохраняются исходные цитаты и ссылки на страницы. PDF отображается постранично; DOCX для просмотра с оформлением преобразуется в PDF через LibreOffice.

### Ключевые компоненты

| Компонент | Назначение |
|---|---|
| `frontend/src/components/DocumentLibrary.jsx` | Библиотека документов с предпросмотром, загрузкой, поиском и папками. |
| `frontend/src/components/DocumentWorkspace.jsx` | Документ и результаты рядом: поля, сводка, риски, редактирование, подтверждение и экспорт. |
| `backend/app.py` | HTTP API, авторизация, загрузка, запуск обработки и сохранение результатов. |
| `backend/jobs.py` — `JobManager` | Выполнение заданий, повторные попытки и восстановление очереди после перезапуска. Состояние заданий хранится в БД. |
| `backend/document_view.py` | Подготовка страниц, отрисовка оригинала и поиск координат цитат для выделения. |
| `backend/extraction.py` — `ExtractionService` | Выбор локального или внешнего обработчика извлечения. |
| `src/parsing.py`, `src/pdf_parser.py`, `src/ocr.py` | Чтение файлов и OCR с сохранением структуры страниц в `DocumentIR`. |
| `src/extraction/` | Схема полей, обработка длинных документов по фрагментам, валидация, суммаризация и анализ рисков. |
| `scripts/` | Проверка окружения, загрузка моделей, запуск сервера и сравнение моделей. |

### Режимы обработки

| Режим | Извлечение | Сводка и риски | Где выполняется обработка |
|---|---|---|---|
| Правила, `compose.yaml` + `compose.rules.yaml` | Четыре атрибута по контекстным правилам | Не используются | CPU, без весов моделей и внешних API. |
| Локальный сервер, `compose.yaml` | `numind/NuExtract3` | `Qwen/Qwen3-8B` | В backend на NVIDIA GPU; доступ backend в интернет закрыт. |
| DeepCode, `compose.yaml` + `compose.api.yaml` | Настраиваемая модель, в примере `qwen3.8-flash-next` | Та же модель через API | Текст отправляется в настроенный внешний API; GPU не требуется. |
| Локальная разработка на Apple Silicon | `numind/NuExtract3-mlx-8bits` через MLX | Transformers | На компьютере разработчика. |

Режим задаётся конфигурацией окружения. Для DeepCode используется файл `.env.api` и дополнительный Compose-файл `compose.api.yaml`.

## Состав системы

| Сервис | Директория / конфигурация | Порты | Описание |
|---|---|---|---|
| **frontend** | `frontend/`, `deploy/nginx.conf` | `8080` на хосте | React-приложение и проксирование `/api/` в backend через Nginx. |
| **backend** | `backend/`, `src/`, `Dockerfile` | `8000`, внутри Docker | FastAPI, очередь заданий и модели в одном процессе API. |
| **db** | `compose.yaml` | `5432`, внутри Docker | PostgreSQL 16: пользователи, сессии, документы, результаты и задания. |
| **model-download** | `scripts/download_models.py`, профиль `setup` | — | Однократная загрузка локальных моделей в volume `models`. |
| **ml-check** | `scripts/ml_check.py`, профиль `validation` | — | Проверка парсинга и реальной генерации на контрольных примерах. |

Постоянные данные хранятся в volumes `database`, `documents`, `models` и `reports`.

## Быстрый старт

### Требования

- Для серверного запуска: Linux, Docker Engine **23+** с BuildKit и Docker Compose **2.30+**.
- Для локальных моделей: NVIDIA GPU, драйвер с поддержкой CUDA 12.8 и NVIDIA Container Toolkit.
- Для DeepCode: адрес OpenAI-совместимого API, ключ и доступ к выбранной модели.
- Для запуска без Docker: Python **3.12–3.13**, `uv`, Node.js **22** и npm. Нужны LibreOffice и Tesseract с языками `rus` и `eng`; в Docker они уже установлены.
- Интернет для сборки образов и первичной загрузки весов.

### Конфигурация

Для локального сервера создайте `.env.server` в корне репозитория:

```bash
cp .env.server.example .env.server
openssl rand -hex 24
```

Запишите сгенерированный пароль в `POSTGRES_PASSWORD`. Основные настройки локального профиля:

```env
BIND_ADDRESS=127.0.0.1
HTTP_PORT=8080
EXTRACTION_BACKEND=local
SUMMARY_BACKEND=local
RISK_BACKEND=local
ML_ALLOW_EXTERNAL=false
```

Значения по умолчанию приведены для `.env.server.example` и `.env.api.example`.

| Переменная | Обязательная | По умолчанию | Описание |
|---|---|---|---|
| `POSTGRES_PASSWORD` | да | Требует замены | Пароль PostgreSQL; используйте сгенерированную hex-строку. |
| `BIND_ADDRESS` | нет | `127.0.0.1` | Адрес хоста, на котором доступен интерфейс. |
| `HTTP_PORT` | нет | `8080` | Порт интерфейса и проксируемого API. |
| `CORS_ORIGINS` | нет | `http://localhost:8080` | Разрешённые origins интерфейса через запятую. |
| `MAX_UPLOAD_SIZE_MB` | нет | `50` | Ограничение backend на размер файла; лимит Nginx также равен 50 МБ. |
| `MAX_PDF_PAGES` | нет | `200` | Максимальное число страниц загружаемого PDF. |
| `JOB_WORKER_COUNT` | нет | `1` | Число фоновых потоков; локальный Compose фиксирует один. |
| `ML_ALLOW_EXTERNAL` | да для API | `false` / `true` | Разрешение внешнего inference; согласовано с выбранным профилем. |
| `EXTRACTION_BACKEND`, `SUMMARY_BACKEND`, `RISK_BACKEND` | нет | `local` / `api` | Обработчики трёх этапов; Compose устанавливает значения профиля. |
| `CONTRACT_MODEL_ID` | нет | `numind/NuExtract3` | Локальная модель извлечения. |
| `CONTRACT_MODEL_QUANTIZATION` | нет | `bf16` | Режим CUDA-модели; `8bit` доступен как альтернативный режим. |
| `SUMMARY_LOCAL_MODEL_NAME` | нет | `Qwen/Qwen3-8B` | Локальная модель сводки и рисков. |
| `ML_KEEP_MODELS_LOADED` | нет | `false` | Удерживать модели в GPU-памяти; при `false` они выгружаются между этапами. |
| `CONTRACT_MODEL_REVISION`, `SUMMARY_LOCAL_MODEL_REVISION` | нет | SHA в `.env.server.example` | Закреплённые ревизии моделей для воспроизводимого развёртывания. |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | да для API | — | Адрес и ключ DeepCode; задаются в `.env.api`. |
| `ML_API_TRUST_ENV` | нет | `false` | Использовать proxy и CA-настройки окружения при обращении к API; включите, если они нужны вашей сети. |
| `ML_API_CONNECT_RETRIES` | нет | `2` | Число повторов установки соединения, от 0 до 3; завершённые запросы не повторяются. |
| `EXTRACTION_API_MODEL`, `SUMMARY_MODEL_NAME`, `RISK_MODEL_NAME` | да для API | `qwen3.8-flash-next` | Идентификаторы моделей в API-профиле. |

Если увеличиваете размер загрузки, измените также `client_max_body_size` в `deploy/nginx.conf`. Для фотографий действуют отдельные ограничения: ширина и высота не меньше 320 пикселей, площадь не больше 40 мегапикселей.

### Запуск

Профиль поставки четырёх атрибутов [pmi-rules-v1](docs/DELIVERY_PROFILE.md): CPU, нативный DOCX, текстовый PDF, PostgreSQL, автоматическое извлечение, OCR и внешние вызовы выключены.

```bash
cp .env.rules.example .env.rules
# Задайте сгенерированный POSTGRES_PASSWORD в .env.rules.
docker compose --env-file .env.rules -f compose.yaml -f compose.rules.yaml build backend frontend
docker compose --env-file .env.rules -f compose.yaml -f compose.rules.yaml up -d --wait
curl --fail http://127.0.0.1:8080/api/health/ready
```

Релиз **`v1.0.0`** включает [замороженный контрольный набор с эталонами](evals/pmi-control-v1/README.md): 36 синтетических договоров, 24 development / 12 holdout, каждый в PDF и DOCX. [Команды воспроизведения](docs/RELEASE_v1.0.0.md) и [правила подсчёта четырёх приёмочных метрик](docs/ACCEPTANCE.md) входят в репозиторий.

Локальный сервер с NVIDIA GPU:

```bash
# Сборка backend и интерфейса.
docker compose --env-file .env.server build

# Первичная загрузка весов, затем проверка моделей до запуска рабочего backend.
docker compose --env-file .env.server --profile setup run --rm model-download
docker compose --env-file .env.server --profile validation run --rm ml-check

# Запуск системы и проверка готовности API/БД.
docker compose --env-file .env.server up -d
curl --fail http://127.0.0.1:8080/api/health/ready
```

Откройте `http://127.0.0.1:8080` и зарегистрируйте учётную запись.

API-профиль DeepCode:

```bash
cp .env.api.example .env.api
# Заполните POSTGRES_PASSWORD, OPENAI_BASE_URL и OPENAI_API_KEY в .env.api.
# SERVER_ENV_FILE=.env.api уже указан в шаблоне.
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml build
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml \
  --profile validation run --rm ml-check
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml up -d
```

Имя модели задаётся по ID из DeepCode `/models`. Интерфейс доступен на `http://127.0.0.1:8080`.

### Запуск отдельных компонентов

Сервисы локального Docker-профиля:

```bash
docker compose --env-file .env.server up -d db
docker compose --env-file .env.server up -d backend
docker compose --env-file .env.server up -d frontend
```

Compose запускает зависимости автоматически.

Для разработки без Docker в корне репозитория:

```bash
cp .env.example .env
uv sync
uv run uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

В другом терминале:

```bash
cd frontend
npm ci
npm run dev
```

Интерфейс: `http://localhost:5173`, API: `http://127.0.0.1:8000`. Vite проксирует `/api/` в backend. По умолчанию используются SQLite `documents.db` и хранилище `uploads/`; пути задаются в `.env` через `DATABASE_URL` и `DOCUMENT_STORAGE_DIR`.

### Остановка

```bash
# Локальный профиль.
docker compose --env-file .env.server down

# API-профиль.
docker compose --env-file .env.api -f compose.yaml -f compose.api.yaml down
```

Данные в volumes сохраняются. Для остановки процессов разработки используйте `Ctrl+C`.

## Тесты

```bash
# Все модульные и API-тесты.
uv run python -m pytest -q

# Проверки извлечения, анализа и оценки корпуса.
uv run python -m pytest -q tests/test_api_extraction.py tests/test_insights_api.py tests/test_corpus_evaluation.py

# Проверка production-сборки интерфейса из корня репозитория.
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

### Вспомогательные скрипты

| Скрипт | Назначение | Когда использовать |
|---|---|---|
| `scripts.check_runtime` | Проверить CUDA, OCR, LibreOffice и наличие весов без генерации. | До запуска локального сервера. |
| `scripts.download_models` | Загрузить модели и вывести фактические ревизии. | Первичная подготовка и обновление весов. |
| `scripts.ml_check` | Проверить парсинг, извлечение 11 реквизитов, сводку и контрольные риски. | Проверка установки с реальными моделями. |
| `scripts.check_deployment` | Загрузить синтетические PDF/DOCX/JPG через HTTP, проверить поля, сводку, риски, оригинал, выделения и подтверждение оператора. | Сквозная проверка запущенного стенда. |
| `scripts.benchmark_models` | Сравнить модели на синтетических примерах с повторными замерами. | Быстрая проверка совместимости и задержки. |
| `scripts.benchmark_dataset` | Сравнить обработку всех файлов корпуса на одинаковых подготовленных входах. | Оценка на реальных договорах; подробности в `evals/README.md`. |

```bash
# PDF, DOCX и OCR без запуска модели.
uv run python -m scripts.ml_check --parsing-only

# Локальная модель и DeepCode на синтетических данных.
uv run python -m scripts.benchmark_models \
  --backends local api --api-model qwen3.8-flash-next \
  --repeats 3 --insights --output tmp/synthetic-comparison.json
```

`--backends` выбирает модели, `--api-model` — ID в DeepCode, `--repeats` — число прогонов, `--insights` добавляет проверку сводки и рисков через API, `--output` задаёт путь отчёта. API-ключ и адрес читаются из окружения или `.env`.

Сравнение на корпусе выполняется этапами `prepare`, `run`, `compare`; `rescore` пересчитывает сохранённые ответы без запуска моделей. Полная разметка — `meta/1.json` … `meta/50.json` из отдельного `meta.zip`. Команды и параметры приведены в [руководстве по оценке моделей](evals/README.md).

## API

При прямом запуске интерактивная документация FastAPI доступна на `http://127.0.0.1:8000/docs`, схема — на `/openapi.json`. Через Docker/Nginx базовый путь API — `http://127.0.0.1:8080/api`, документация — `/api/docs`, схема — `/api/openapi.json`. Пути в таблицах ниже указаны относительно backend, без префикса `/api`.

### Авторизация (`/auth`, `/users`)

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/auth/register` | Зарегистрировать пользователя: `username`, `email`, `password`. |
| `POST` | `/auth/login` | Войти по `username` и `password`, получить `session_token`. |
| `POST` | `/auth/logout` | Завершить сессию, передав `session_token` в JSON. |
| `POST` | `/auth/validate` | Проверить `session_token`. |
| `GET` | `/users/me` | Получить профиль текущего пользователя. |
| `PUT` | `/users/me` | Обновить профиль текущего пользователя. |
| `DELETE` | `/users/me` | Удалить текущую учётную запись и связанные данные. |

Для защищённых запросов передавайте заголовок `Authorization: Bearer SESSION_TOKEN`, подставляя токен из ответа `/auth/login`.

### Документы (`/documents`)

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/documents` | Загрузить `file` через `multipart/form-data`; необязательные `folder_id` и `template_id`. Возвращает `202`, подготовка выполняется в фоне. |
| `POST` | `/documents/batch` | Загрузить несколько `files` в одном multipart-запросе; ответ `207` с отдельным результатом для каждого файла. |
| `GET` | `/documents` | Реестр с полями, поиском и пагинацией; `sort_by=created_at/contract_date/total_amount`, `sort_order=asc/desc`. |
| `GET` | `/documents/{document_id}` | Статус, ошибки и сохранённые результаты документа. |
| `POST` | `/documents/{document_id}/analyze` | Повторно извлечь поля в ту же запись реестра; возвращает текущий документ. |
| `POST` | `/documents/{document_id}/metadata` | Совместимый маршрут постановки извлечения в очередь, ответ `202`. |
| `PATCH` | `/documents/{document_id}/metadata` | Сохранить полный объект редактируемых `fields`. |
| `PATCH` | `/documents/{document_id}/review` | Подтвердить результат оператором или вернуть на проверку. |
| `POST` | `/documents/{document_id}/insights` | Сформировать заново сводку; ошибки возвращаются в `errors`. |
| `POST` | `/documents/{document_id}/risks` | Проверить поставку или услуги с выбранной стороны; сохранить основания, цитаты и охват проверки. |
| `GET` | `/documents/{document_id}/content` | Получить подготовленный текст по страницам. |
| `GET` | `/documents/{document_id}/pages/{page_number}/image` | Получить изображение страницы оригинала. |
| `GET` | `/documents/{document_id}/preview` | Получить уменьшенное изображение первой страницы для библиотеки. |
| `POST` | `/documents/{document_id}/source-location` | Найти координаты цитаты по `evidence` и необязательному `page`. |
| `GET` | `/documents/{document_id}/file` | Скачать исходный файл. |
| `PATCH` | `/documents/{document_id}` | Переместить документ в папку или общий список, передав `folder_id`. |
| `DELETE` | `/documents/{document_id}` | Удалить документ и связанные данные. |

**Тело запроса `POST /documents/{document_id}/risks`:**

В интерфейсе пользователь выбирает свою компанию из сторон договора. Роль для проверки определяется по реквизитам, тип договора подставляется автоматически; параметры API ниже сохраняют прежний формат.

```json
{
  "contract_type": "supply",
  "user_side": "customer",
  "jurisdiction": "RU",
  "scope_confirmed": true
}
```

`contract_type`: `supply` — поставка, `services` — услуги. `user_side`:
`customer` — покупатель/заказчик, `provider` — поставщик/исполнитель.
Профиль предназначен для обычных B2B-договоров по праву РФ. Ответ содержит
`metadata.risk_review`: статус, параметры, результаты правил, связанные цитаты,
основания и охват обработки. `complete` означает завершение проверок каталога,
а не юридическую безопасность договора. При `failed` или `unsupported` список
новых рисков не публикуется. Правка полей сбрасывает предыдущую проверку.

**Тело запроса `PATCH /documents/{document_id}/review`:**

```json
{
  "confirmed": true
}
```

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `confirmed` | `boolean` | да | `true` — подтвердить проверку; `false` — вернуть на проверку. |

Статусы документа: `processing` → `ready` → `processing` → `extracted`; при ошибке — `failed`. После `ready` клиент вызывает `/analyze`; веб-интерфейс делает это автоматически для новых загрузок. Подтверждение оператора хранится в `review_status`: `pending` / `reviewed`.

**Статусы / коды ответа:**

| Код | Статус | Описание |
|---|---|---|
| `200` | `OK` | Запрос выполнен; для фоновой обработки результат отслеживается через GET документа. |
| `202` | `Accepted` | Загрузка или извлечение через `/metadata` поставлены в очередь. |
| `400` | `Bad Request` | Некорректный запрос или формат файла. |
| `401` | `Unauthorized` | Требуется действующая сессия. |
| `403` | `Forbidden` | Недостаточно прав. |
| `404` | `Not Found` | Ресурс не найден. |
| `409` | `Conflict` | Операция недоступна в текущем состоянии документа. |
| `413` | `Content Too Large` | Превышен размер загрузки. |
| `422` | `Unprocessable Entity` | Данные не соответствуют схеме запроса. |
| `503` | `Service Unavailable` | Сервис временно недоступен. |

### Служебные маршруты и организация документов

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/ping` | Проверка доступности HTTP-сервиса. |
| `GET` | `/health/ready` | Проверка API и соединения с БД; без запуска модели. |
| `GET` | `/runtime/profile` | Настройки закреплённого профиля и хеши исходников без секретов. |
| `GET`, `POST` | `/folders` | Список папок и создание папки. |
| `PATCH`, `DELETE` | `/folders/{folder_id}` | Переименование и удаление папки. |
| `GET` | `/stats` | Статистика обработки. |

## Логирование

Backend использует стандартный Python `logging` и access-логи Uvicorn. Формат сообщений приложения:

```text
2026-10-26 10:15:00,123 - backend.app - INFO - Metadata saved for document 42
```

- Конфигурация: `logging.basicConfig` в `backend/app.py`.
- Обработчик: `StreamHandler`, вывод в stderr; access-логи Uvicorn — в stdout.
- Хранение и ротация: logging driver Docker и настройки сервера.
- Уровни: `INFO`, `WARNING`, `ERROR`.
- Содержимое: этапы обработки, идентификаторы документов, длительность, число токенов и ошибки.

```bash
docker compose --env-file .env.server logs -f backend
docker compose --env-file .env.server logs --tail 100 frontend db
```

Для API-профиля используйте те же команды с `--env-file .env.api -f compose.yaml -f compose.api.yaml`.

## Сетевая конфигурация

Сервисы обращаются друг к другу по DNS-именам `backend` и `db`. Подсети и IP-адреса назначает Docker.

| Сеть | Подсеть | Участники | Назначение |
|---|---|---|---|
| `private`, `internal: true` | Автоматически | `frontend`, `backend`, `db`, `ml-check` | Внутренние HTTP/SQL-соединения. |
| `edge` | Автоматически | `frontend` | Публикация интерфейса на `127.0.0.1:8080`. |
| `download` | Автоматически | `model-download` | Скачивание весов Hugging Face. |
| `inference`, API-профиль | Автоматически | `backend`, `ml-check` | Запросы в DeepCode. |

API на `8000` и PostgreSQL на `5432` не публикуются на хосте. Для доступа из сети измените `BIND_ADDRESS`, укажите адрес интерфейса в `CORS_ORIGINS` и подключите HTTPS через reverse proxy сервера. В режиме разработки frontend и backend слушают отдельные порты `5173` и `8000`.

## Документация по компонентам

- [Контекст проекта](docs/PROJECT_CONTEXT.md) — состояние реализации, результаты и источники решений.
- [Подготовка к ПМИ](docs/PMI_ACTION_PLAN.md) — оставшиеся работы и критерии завершения.
- [API](docs/API.md) — маршруты и примеры запросов.
- [Развёртывание](docs/DEPLOYMENT.md) — Docker, GPU, модели и API-профиль.
- [Эксплуатация](docs/OPERATIONS.md) — задания, ограничения загрузки и восстановление.
- [ML-аудит](docs/ML_AUDIT.md) — описание проверок ML.
- [Оценка моделей](evals/README.md) — сравнение моделей на корпусе.
- [Демонстрация](docs/DEMO.md) — подготовка стенда и сценарий показа.
- [Эталонная разметка](meta/README.md) — формат данных для оценки извлечения.
