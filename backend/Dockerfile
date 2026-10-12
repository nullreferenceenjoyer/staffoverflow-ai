FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Зависимости ставим отдельным слоем: он пересобирается только при изменении pyproject.toml.
# Сам пакет после этого удаляем из site-packages, чтобы код брался только из /app.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y hr-edu-backend \
    && rm -rf app build *.egg-info

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh ./

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/storage \
    && chown -R appuser /app /data
USER appuser

EXPOSE 8000
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
# --proxy-headers: за nginx реальный адрес клиента приходит в X-Forwarded-For (нужен для аудита)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
