ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="115-media-hub" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.description="FastAPI media automation hub for 115 and AList/OpenList" \
      org.opencontainers.image.source="https://github.com/xianer235/115-media-hub"
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1 \
    UVICORN_ACCESS_LOG=0

WORKDIR /app

# 先安装依赖，最大化 Docker 层缓存；uvicorn[standard] 会启用 uvloop/httptools 的二进制轮子。
COPY requirements.txt .
RUN pip install --prefer-binary -r requirements.txt

# 只复制运行所需文件，避免本地预览、备份、设计稿进入镜像。
COPY app ./app
COPY static ./static
COPY templates ./templates
COPY main.py 115-magnet-helper-webhook.user.js ./

RUN python -m compileall -q app main.py

COPY version.json ./

EXPOSE 18080

# 启动（默认关闭 access log，避免轮询接口刷屏；可通过 UVICORN_ACCESS_LOG=1 开启）
CMD ["sh", "-c", "if [ \"${UVICORN_ACCESS_LOG:-0}\" = \"1\" ]; then exec python -m uvicorn main:app --host 0.0.0.0 --port 18080; else exec python -m uvicorn main:app --host 0.0.0.0 --port 18080 --no-access-log; fi"]
