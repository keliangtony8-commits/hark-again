FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" "websockets>=15,<18" docker==7.* httpx==0.27.*
WORKDIR /app
COPY runner.py .
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "9000"]
