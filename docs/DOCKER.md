# Переносимое развёртывание Docker

`compose.portable.yaml` запускает интерфейс, FastAPI и PostgreSQL без NVIDIA GPU,
Torch и скачивания весов моделей. Нужны Docker Desktop (macOS/Windows, Linux
containers) либо Docker Engine с Compose 2.30+ (Linux). Образы собираются для
`linux/amd64` и `linux/arm64`; при обычной сборке выбирается архитектура хоста.
Для локальных моделей на NVIDIA остаётся отдельный `compose.yaml`.

## Запуск из исходников

```bash
# Создайте .env.docker с настройками режима правил из DELIVERY_PROFILE.md.
# Укажите DOCKER_ENV_FILE=.env.docker.
openssl rand -hex 24
# Вставьте сгенерированную строку в POSTGRES_PASSWORD файла .env.docker.
docker compose --env-file .env.docker -f compose.portable.yaml up -d --build --wait
```

В PowerShell создайте `.env.docker` в редакторе с теми же параметрами
и задайте длинный случайный пароль из ASCII-букв и цифр.
Не меняйте пароль при повторном запуске существующего volume PostgreSQL.

Откройте <http://localhost:8080> и зарегистрируйте пользователя.
Проверка готовности: <http://localhost:8080/api/health/ready>.
Пароль, документы и ключи в образы не включаются; `.env.docker` не коммитится.
Для доступа из локальной сети задайте `BIND_ADDRESS=0.0.0.0`, нужный `HTTP_PORT`
и соответствующий адрес в `CORS_ORIGINS`.

По умолчанию включён профиль **pmi-rules-v1**: извлечение четырёх атрибутов
из текстовых PDF и нативных DOCX без внешних вызовов. Сводка, риски и OCR
в этом профиле недоступны. Это тот же профиль, который описан в
[DELIVERY_PROFILE.md](DELIVERY_PROFILE.md).

## Локальное извлечение и работа через API

В [README](../README.md#запуск) приведены два готовых варианта запуска из исходников:

| Назначение | Окружение | Compose | Ресурсы |
|---|---|---|---|
| Разработка через API на всех стадиях | `.env.api` | `compose.yaml` + `compose.api.yaml` | CPU, доступ к API; без GPU и весов |
| Локальное извлечение NuExtract3, Qwen API для сводки и рисков | `.env.server` | `compose.yaml` + `compose.local-extraction.yaml` | NVIDIA GPU, веса NuExtract3, доступ к API |

Имена моделей задаются в окружении. Для локального извлечения используется CUDA-образ
`Dockerfile`; `compose.api.yaml` выбирает CPU-вариант этого Dockerfile для
разработки. `Dockerfile.portable` — отдельный облегчённый вариант для правил
и API, описанный ниже; локальный NuExtract3 в нём не запускается.

## Извлечение через API

Следующие настройки выбирают API и для извлечения полей. Каждый backend
задаётся в окружении независимо от остальных; общий код не привязан к модели
из примера. Образ и ресурсы Compose выбираются под эти настройки.

В том же `.env.docker` установите:

```dotenv
DELIVERY_PROFILE=custom
EXTRACTION_BACKEND=api
SUMMARY_BACKEND=api
RISK_BACKEND=api
ML_ALLOW_EXTERNAL=true
DOCX_USE_RENDERED_PAGES=true
ALLOW_OCR_UPLOADS=true
OPENAI_BASE_URL=https://your-service.example/v1
OPENAI_API_KEY=your-key
EXTRACTION_API_MODEL=your-model-id
SUMMARY_MODEL_NAME=your-model-id
RISK_MODEL_NAME=your-model-id
```

Используйте согласованный сервис: этот режим отправляет ему текст договоров.
Выберите фактический ID модели из его `/models`. Пересоздайте сервисы той же
командой `up -d --wait` (пересборка образа для изменения настроек не нужна).
В контейнере `localhost` — сам контейнер; для API на хосте Docker Desktop
используйте `host.docker.internal`. На Linux настройте доступный контейнеру
адрес сервиса. Адрес API и ключ задаются только на целевом компьютере.

## Перенос готовых образов без пересборки

На компьютере сборки сохраните backend, frontend и PostgreSQL:

```bash
docker image save -o contract-intelligence-images.tar \
  contract-intelligence-backend:portable \
  contract-intelligence-frontend:portable postgres:16-alpine
```

Перенесите архив и `compose.portable.yaml` на целевой компьютер.
Создайте там `.env.docker` с параметрами режима правил или API. Исходники для запуска готовых образов не нужны:

```bash
docker image load -i contract-intelligence-images.tar
# Создайте .env.docker с настройками режима правил из DELIVERY_PROFILE.md.
# Укажите DOCKER_ENV_FILE=.env.docker.
# Задайте новый POSTGRES_PASSWORD и, при необходимости, настройки API.
docker compose --env-file .env.docker -f compose.portable.yaml up -d --no-build --pull never --wait
```

Одноархитектурный архив используйте на компьютере с той же архитектурой.
Для общего архива amd64 + arm64 соберите оба приложения через Buildx
(Docker Desktop / Docker Engine 29+ с containerd image store):

```bash
docker buildx build --platform linux/amd64,linux/arm64 --load \
  -f Dockerfile.portable -t contract-intelligence-backend:portable .
docker buildx build --platform linux/amd64,linux/arm64 --load \
  -f frontend/Dockerfile -t contract-intelligence-frontend:portable .
docker pull --platform linux/amd64 postgres:16-alpine
docker pull --platform linux/arm64 postgres:16-alpine
# Затем выполните image save, как выше.
```

Правила multi-platform сборки: [документация Docker](https://docs.docker.com/build/building/multi-platform/).
Публикация в registry не требуется. Архив содержит приложение и зависимости;
пользователи, загруженные документы и содержимое БД остаются в volumes исходного
компьютера. Перенос существующей БД требует отдельного резервного копирования.

## Обслуживание

```bash
docker compose --env-file .env.docker -f compose.portable.yaml ps
docker compose --env-file .env.docker -f compose.portable.yaml logs --tail 100 backend
docker compose --env-file .env.docker -f compose.portable.yaml down
```

`down` сохраняет volumes `database` и `documents`. Не добавляйте `--volumes`,
если данные нужны. После обновления кода выполните `up -d --build --wait`;
после загрузки нового архива образов — `up -d --no-build --pull never --wait`.
