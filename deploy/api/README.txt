T1 Contract Intelligence — Linux x86_64, Qwen через API

Исходники: https://github.com/Vik0t/contract-intelligence-t1
Версия: deploy-2026-11-20-api. Точный commit и ID образов — build-manifest.json.
Дата сборки: 20.11.2026 (Asia/Novosibirsk)

В комплекте: backend FastAPI с LibreOffice и OCR rus/eng, frontend Nginx,
PostgreSQL 16, Compose, шаблон окружения, исходники и протокол проверки.
GPU, CUDA и локальные веса моделей для этой поставки не требуются.
Нужны Linux x86_64, Docker Engine 23+, Docker Compose 2.30+ и доступ
контейнеров к выбранному OpenAI-совместимому API Qwen.
Пароли, API-ключи, документы и данные существующей установки не включены.

Первый запуск (в каталоге распакованного комплекта):

    ./load-images.sh
    ./init-env.sh

Откройте .env.server в редакторе и заполните API-ключ:
    OPENAI_API_KEY=ваш_ключ

DeepCode и модель уже настроены в шаблоне:
    OPENAI_BASE_URL=https://deepcode.ci.nsu.ru/api/v1
    EXTRACTION_API_MODEL=qwen3.8-flash-next
    SUMMARY_MODEL_NAME=qwen3.8-flash-next
    RISK_MODEL_NAME=qwen3.8-flash-next

DEEPCODE_ENABLE_THINKING=false выключает скрытое рассуждение.
Текст документов будет отправляться в настроенный API.
Внешний сервис должен поддерживать /models и /chat/completions.

Для доступа по IP сервера задайте BIND_ADDRESS=0.0.0.0,
HTTP_PORT=8080 и CORS_ORIGINS=http://IP_СЕРВЕРА:8080.
При reverse proxy можно оставить BIND_ADDRESS=127.0.0.1 и вписать внешний
HTTPS URL в CORS_ORIGINS. Backend и PostgreSQL не публикуют порты хоста.

Запуск:

    ./compose.sh up -d --no-build --pull never --wait --wait-timeout 180
    ./check-api.sh
    curl --fail http://127.0.0.1:8080/api/health/ready

Интерфейс: http://127.0.0.1:8080 либо настроенный адрес сервера.
Зарегистрируйте учётную запись через интерфейс.
check-api.sh проверяет доступ и ID модели без генерации.
Healthcheck подтверждает доступность приложения и БД; он не проверяет API Qwen.

Необязательная сквозная проверка с реальными вызовами API на синтетических
PDF/DOCX/JPG (расходует токены, создаёт отдельную тестовую учётную запись):

    ./compose.sh exec -T backend python -m scripts.check_deployment --url http://frontend:8080 --output /data/reports/api-check.json

Отчёт этой проверки можно выгрузить:

    ./compose.sh cp backend:/data/reports/api-check.json ./api-check.json

Состояние, журналы и остановка:

    ./compose.sh ps
    ./compose.sh logs --tail 100 backend
    ./compose.sh down

Тома database и documents сохраняются при down. Не добавляйте -v.
Пароль PostgreSQL автоматически создаётся init-env.sh и хранится в .env.server
с правами 0600. Сохраните его вместе с БД; повторный init-env.sh его не меняет.

Протокол реальной проверки: live-validation-2026-11-20.json.
Идентификаторы образов и исходников: build-manifest.json.
Реальные вызовы DeepCode проверены локально на синтетических PDF/DOCX/JPG.
Ключ API хранится только в настройках работающего локального стенда.
Проверки на GitHub выполняются без API-ключа; они не повторяют генерацию Qwen.

Воспроизведение сборки:

    mkdir source
    tar -xzf source.tar.gz -C source
    cd source
    docker build --platform linux/amd64 -f Dockerfile.portable -t contract-intelligence-backend:deploy-2026-11-20-api .
    docker build --platform linux/amd64 -f frontend/Dockerfile -t contract-intelligence-frontend:deploy-2026-11-20-api .
