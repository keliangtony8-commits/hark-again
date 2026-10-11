FROM python:3.12-slim
WORKDIR /srv
# ffmpeg：把 App 的 m4a、网页的 webm 录音转成语音识别接口收的 wav
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
RUN useradd -u 1000 -m app
# 与沙盒同一 uid，项目文件双方都能读写（Dockerfile 指令行尾不能写注释）
USER app
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
