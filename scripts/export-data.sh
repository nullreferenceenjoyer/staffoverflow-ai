#!/bin/sh
# Собирает переносной архив данных: дамп базы и локальные файлы seed/ (в git их нет).
#
#   sh scripts/export-data.sh
#
# Результат — export/hr_edu_data_ГГГГММДД_ЧЧММ.tar.gz. В архиве ФИО из приказов и все
# пользователи: передавайте его только туда, где ему можно лежать.
set -eu
cd "$(dirname "$0")/.."

stamp=$(date +%Y%m%d_%H%M)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/seed" export

echo "Дамп базы…"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
    > "$work/hr_edu.dump"

# demo.json лежит в репозитории, остальные файлы seed/ — локальные
for file in seed/*.json; do
    [ "$file" = "seed/demo.json" ] || cp "$file" "$work/seed/"
done

revision=$(docker compose exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"' \
    | tr -d '\r')
printf 'created=%s\nmigration=%s\n' "$(date '+%Y-%m-%d %H:%M')" "$revision" > "$work/VERSION"

archive="export/hr_edu_data_$stamp.tar.gz"
tar -czf "$archive" -C "$work" .
echo "Готово: $archive"
echo "Перенести: склонировать репозиторий, создать .env и запустить"
echo "  sh scripts/import-data.sh $archive"
