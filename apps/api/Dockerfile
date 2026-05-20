FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

RUN pip install --no-cache-dir uv hatchling

COPY packages /app/packages
COPY apps/api /app/apps/api

RUN pip install --no-cache-dir /app/packages/shared/python
RUN if [ -d /app/packages/sentinelrag-sdk/python ]; then pip install --no-cache-dir /app/packages/sentinelrag-sdk/python; fi
RUN pip install --no-cache-dir /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
