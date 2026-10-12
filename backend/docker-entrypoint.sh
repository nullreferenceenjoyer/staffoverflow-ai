#!/bin/sh
set -e

# Миграции и справочники накатывает только API-контейнер, воркер ждёт его готовности
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    alembic upgrade head
    python -m app.seed
fi

exec "$@"
