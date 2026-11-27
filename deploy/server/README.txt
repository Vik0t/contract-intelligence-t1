T1 Contract Intelligence 1.0.0 — NuExtract3 локально, Qwen через DeepCode

Исходники: https://github.com/Vik0t/contract-intelligence-t1
Версия, дата сборки, точный commit и ID образов — build-manifest.json.

В комплекте: CUDA-backend FastAPI с LibreOffice и OCR rus/eng, frontend Nginx,
PostgreSQL 16, Compose, шаблон окружения, исходники и протокол проверки.
Поля извлекает исходная модель numind/NuExtract3 на NVIDIA GPU.
Ревизия: c99dc8f5641b866aa0192b6ea78f84bf9f3535f1; штатный режим BF16.
Qwen qwen3.8-flash-next через DeepCode используется только для сводки и рисков.
Это начальные настройки. Backend и модель каждой стадии
меняются в .env.server; Compose не переопределяет эти параметры.
Нужны Linux x86_64, NVIDIA GPU и Container Toolkit, драйвер для CUDA 12.8,
Docker Engine 23+, Docker Compose 2.30+ и доступ к DeepCode.
Веса NuExtract3 не включены в образы; они устанавливаются отдельно в volume
models. При запуске backend использует их только из локального кэша.
Пароли, API-ключи, документы и данные существующей установки не включены.

Первый запуск (в каталоге распакованного комплекта):

    ./load-images.sh
    ./init-env.sh

Откройте .env.server в редакторе и заполните API-ключ:
    OPENAI_API_KEY=ваш_ключ

DeepCode и модель уже настроены в шаблоне:
    OPENAI_BASE_URL=https://deepcode.ci.nsu.ru/api/v1
    SUMMARY_MODEL_NAME=qwen3.8-flash-next
    RISK_MODEL_NAME=qwen3.8-flash-next

DEEPCODE_ENABLE_THINKING=false выключает скрытое рассуждение.
Текст и извлечённые поля передаются в API для сводки и анализа рисков.
В этом шаблоне само извлечение полей выполняется локально.
Внешний сервис должен поддерживать /models и /chat/completions.

Для доступа по IP сервера задайте BIND_ADDRESS=0.0.0.0,
HTTP_PORT=8080 и CORS_ORIGINS=http://IP_СЕРВЕРА:8080.
При reverse proxy можно оставить BIND_ADDRESS=127.0.0.1 и вписать внешний
HTTPS URL в CORS_ORIGINS. Backend и PostgreSQL не публикуют порты хоста.

Запуск:

    ./compose.sh --profile setup run --rm model-download
    ./compose.sh up -d --no-build --pull never --wait --wait-timeout 180
    ./check-api.sh
    curl --fail http://127.0.0.1:8080/api/health/ready

Интерфейс: http://127.0.0.1:8080 либо настроенный адрес сервера.
Зарегистрируйте учётную запись через интерфейс.
model-download загружает модели только для стадий с backend=local.
В шаблоне это NuExtract3. Проверки GPU и весов зависят от выбранных backend.
check-api.sh проверяет OpenAI-совместимый API и ID моделей выбранных API-стадий
без генерации. Если стадий с backend=api нет, проверка пропускается.
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

Воспроизведение сборки:

    mkdir source
    tar -xzf source.tar.gz -C source
    cd source
    docker build --platform linux/amd64 -f Dockerfile -t contract-intelligence-backend:1.0.0 .
    docker build --platform linux/amd64 -f frontend/Dockerfile -t contract-intelligence-frontend:1.0.0 .
