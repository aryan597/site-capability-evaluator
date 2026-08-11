FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# All configuration comes from env at runtime:
#   CATALOG_BASE, LLM_PROVIDER, LLM_MODEL, LLM_API_KEY (or ANTHROPIC_API_KEY),
#   CATALOG_TIMEOUT_S, LLM_MAX_CONCURRENCY
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
