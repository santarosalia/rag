FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY constraints ./constraints
COPY src ./src
COPY configs ./configs
COPY alembic ./alembic
COPY alembic.ini ./

# Host driver 570.x = CUDA 12.8. PyPI torch defaults to cu130 and will fail at runtime.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu128 \
    -c constraints/torch-cu128.txt \
    -e .

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
