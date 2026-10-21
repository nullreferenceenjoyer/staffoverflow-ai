#!/bin/sh
# Разворачивает архив из scripts/export-data.sh в свежем клоне репозитория.
#
#   sh scripts/import-data.sh hr_edu_data_….tar.gz              файлы seed/ + база из дампа
#   sh scripts/import-data.sh hr_edu_data_….tar.gz --seed-only  только файлы seed/:
#                                                               база заполнится при запуске
#
# Нужен .env (скопируйте .env.example и задайте пароли). База в дампе заменяет текущую.
set -eu
cd "$(dirname "$0")/.."

archive=${1:?укажите архив: sh scripts/import-data.sh hr_edu_data_….tar.gz}
mode=${2:-}
[ -f .env ] || { echo "Нет .env: скопируйте .env.example в .env и задайте пароли" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar -xzf "$archive" -C "$work"
[ -f "$work/VERSION" ] && cat "$work/VERSION"

mkdir -p seed
cp "$work"/seed/*.json seed/
echo "Файлы данных разложены в seed/"

if [ "$mode" = "--seed-only" ] || [ ! -f "$work/hr_edu.dump" ]; then
    echo "База заполнится из seed/ при первом запуске: docker compose up -d --build"
    exit 0
fi

echo "Поднимаю базу…"
docker compose up -d db
until docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        >/dev/null 2>&1; do
    sleep 1
done

# API и воркер не должны писать в базу, пока она восстанавливается
docker compose stop api worker >/dev/null 2>&1 || true
echo "Восстанавливаю базу из дампа…"
docker compose exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
    < "$work/hr_edu.dump"

echo "Запускаю систему…"
docker compose up -d --build
echo "Готово. Вход — пользователями из перенесённой базы."
