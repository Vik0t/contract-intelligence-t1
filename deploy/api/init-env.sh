#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -e .env.server ]; then
    printf '%s\n' '.env.server уже существует; настройки сохранены.'
    exit 0
fi
umask 077
db_password=$(openssl rand -hex 24)
set -C
sed "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$db_password/" .env.server.example > .env.server
printf '%s\n' '.env.server создан. Заполните OPENAI_BASE_URL и OPENAI_API_KEY и проверьте ID модели Qwen.'
