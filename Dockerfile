FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/root/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY prompts ./prompts
COPY migrations ./migrations
COPY docs ./docs
COPY scripts ./scripts

RUN uv sync --frozen

CMD ["uv", "run", "buratino", "worker", "--max-jobs", "1"]
