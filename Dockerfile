FROM python:3.11-slim

WORKDIR /app

# 仅复制依赖清单先验安装，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码（.dockerignore 已排除 .env / 缓存 / 索引产物）
COPY . .

# 构建向量索引：无 API Key 时自动用本地兜底向量，保证零成本可运行
RUN python scripts/build_index.py || true

# Hugging Face Spaces 以 uid 1000 运行，确保运行期可写目录（日志/看板产物）
RUN mkdir -p data/logs data/generated data/index && chmod -R 777 data

# PORT: Render 会在运行时注入；HF Spaces 默认 7860（与 README 中 app_port 一致）
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
