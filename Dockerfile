# ---------- 构建阶段：安装 Python 依赖 ----------
FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 运行阶段：最小化生产镜像 ----------
FROM python:3.12-slim AS runtime

LABEL maintainer="harness" \
      description="Harness AI 角色扮演引擎"

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r harness --gid 1000 \
    && useradd -r -g harness --uid 1000 --home-dir /app harness

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

RUN chmod +x /app/deploy/entrypoint.sh \
    /app/deploy/scripts/*.sh \
    /app/deploy/healthcheck.py \
    /app/deploy/scripts/init_admin.py \
    /app/deploy/scripts/init_db.py \
    && mkdir -p /app/data \
    && chown -R harness:harness /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HARNESS_DATA_DIR=/app/data \
    WEB_PORT=7860 \
    API_PORT=8000 \
    FLASK_ENV=production

EXPOSE 7860 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python /app/deploy/healthcheck.py || exit 1

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["web"]
