# 云浏览器服务：自带 Chromium 和依赖的官方镜像
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.30.* playwright==1.47.*
WORKDIR /app
COPY service.py .
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "9100"]
