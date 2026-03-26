FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="115-strm-web" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.description="FastAPI service to convert 115 directory trees into STRM files" \
      org.opencontainers.image.source="https://github.com/xianer235/115-strm-web"
ENV APP_VERSION=${APP_VERSION}

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

# 启动（确保文件名是 main.py，app 对象名是 app）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18080"]
