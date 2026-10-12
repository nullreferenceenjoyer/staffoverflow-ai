#!/bin/sh
# Запускает llama.cpp с моделью из /models: либо LLM_MODEL_FILE, либо первый найденный .gguf.
set -e

if [ -n "${LLM_MODEL_FILE:-}" ]; then
    model="/models/${LLM_MODEL_FILE}"
else
    model="$(ls /models/*.gguf 2>/dev/null | head -n 1)"
fi

if [ -z "$model" ] || [ ! -f "$model" ]; then
    echo "В папке models/ нет файла .gguf. Скачайте модель и положите её туда." >&2
    exit 1
fi

echo "Модель: $model, контекст: ${LLM_CONTEXT:-8192}"
# --jinja включает шаблон чата из модели, без него не работает вызов инструментов
set -- /app/llama-server --model "$model" --host 0.0.0.0 --port 8080 \
    --ctx-size "${LLM_CONTEXT:-8192}" --jinja
if [ -n "${LLM_THREADS:-}" ]; then
    set -- "$@" --threads "$LLM_THREADS"
fi
exec "$@"
