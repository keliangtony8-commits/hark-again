# 每个项目一个容器的基础镜像：常用语言和工具，非 root 运行
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 dev
USER dev
WORKDIR /workspace
CMD ["sleep", "infinity"]
