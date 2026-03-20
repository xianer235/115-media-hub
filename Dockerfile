FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim

WORKDIR /app

# 安装运行依赖（itsdangerous 是 SessionMiddleware 必需）
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    itsdangerous
# 复制当前目录下所有文件
COPY . .
EXPOSE 18080

# 启动（确保文件名是 main.py，app 对象名是 app）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18080"]
