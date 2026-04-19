FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="115-media-hub" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.description="FastAPI media automation hub for 115 and AList/OpenList" \
      org.opencontainers.image.source="https://github.com/xianer235/115-media-hub"
ENV UVICORN_ACCESS_LOG=0 \
    LOG_BRIEF_MODE=1

WORKDIR /app

# 安装转码和下载必须的工具
RUN apt-get update && apt-get install -y \
    curl \
    libc-bin \
    && rm -rf /var/lib/apt/lists/*

# 安装依赖（itsdangerous 是 SessionMiddleware 必需的）
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic \
    python-multipart \
    starlette \
    itsdangerous\
    requests
# 复制当前目录下所有文件
COPY . .
EXPOSE 18080

# 启动（默认关闭 access log，避免轮询接口刷屏；可通过 UVICORN_ACCESS_LOG=1 开启）
CMD ["sh", "-c", "if [ \"${UVICORN_ACCESS_LOG:-0}\" = \"1\" ]; then exec uvicorn main:app --host 0.0.0.0 --port 18080; else exec uvicorn main:app --host 0.0.0.0 --port 18080 --no-access-log; fi"]
