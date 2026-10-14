# 云浏览器服务：自带 Chromium 和依赖的官方镜像
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
# 中文字体：网页截图和渲染的 PDF / 长图里中文不变方块（v2.22）
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.30.* playwright==1.47.*
WORKDIR /app
COPY service.py egress.py tabs.py forms.py dialogs.py frames.py shadow.py ./
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "9100"]
