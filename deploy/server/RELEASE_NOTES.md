Серверный комплект 1.0.0 для Linux x86_64: поля извлекает исходный `numind/NuExtract3` на NVIDIA GPU; сводку и риски формирует Qwen `qwen3.8-flash-next` через DeepCode.

В архиве: backend с OCR и LibreOffice, frontend Nginx, PostgreSQL 16, Compose, шаблон окружения, исходники, идентификаторы образов и SHA-256. API-ключи и пользовательские документы не включены.

Точный состав проверки и фактические результаты NuExtract3 приведены в `a10-validation.json` проверенного комплекта. Прежний API-прогон `live-validation-2026-11-20.json` не является проверкой этой конфигурации. Веса NuExtract3 загружаются отдельно в volume `models`.

Исправлена проверка развертывания при автоматическом запуске извлечения: она принимает уже обработанный документ и учитывает одновременный запуск фонового задания.

После распаковки: `./load-images.sh`, `./init-env.sh`, заполнить `OPENAI_API_KEY` в `.env.server`, выполнить `./compose.sh --profile setup run --rm model-download`, затем `./compose.sh up -d --no-build --pull never --wait` и `./check-api.sh`. Нужны NVIDIA GPU и Container Toolkit. Подробности — `README.txt` внутри архива.
