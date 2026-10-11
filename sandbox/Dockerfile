FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.30.* docker==7.*
WORKDIR /app
COPY runner.py .
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "9000"]
