# 大狗嚼电竞管理系统 - 后端 Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 换 Debian 国内源（加速 apt 下载）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# 系统依赖（libgomp1 是 chromadb/onnxruntime 需要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存），用国内 pip 源加速
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 复制后端代码
COPY backend/ .

# 静态资源目录（头像、壁纸、知识库图片）
VOLUME ["/app/chroma_db", "/app/qdrant_db"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
