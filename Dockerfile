FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV TZ=Asia/Kolkata \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COMPOSE_BAKE=true \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=90 \
    UV_NO_PROGRESS=1 \
    UV_CONCURRENT_DOWNLOADS=10 \
    PATH="/app/.venv/bin:$PATH" \
    IPYTHONDIR=/app/.ipython

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tzdata \
        curl \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && ln -sf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime \
    && echo "Asia/Kolkata" > /etc/timezone

WORKDIR /app

COPY ./pyproject.toml uv.lock ./
COPY modules/ipython_startup.py /app/modules/ipython_startup.py


# Install dependencies with BuildKit cache mount for uv cache
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Adding Aliases
RUN echo 'alias ipython="uv run ipython"' >> /root/.bashrc && \
    echo 'alias cls="clear"' >> /root/.bashrc

# Setup ipython startup
RUN mkdir -p /app/.ipython/profile_default/startup/ && \
    cp /app/modules/ipython_startup.py /app/.ipython/profile_default/startup/auto_reload.py