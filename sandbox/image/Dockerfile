# 每个工作区一个容器的基础镜像：常用语言和工具，非 root 运行（没有 sudo / apt）。
# 系统软件只能在这里预装；pip / npm 装的东西落在工作区 ~/.local，换镜像也不丢（见 workspace-env.sh）。
# 预装清单改了要同步 backend/app/workspaces.py PREINSTALLED（模型据此知道有什么、缺了别去 apt）。
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        git nodejs npm curl ca-certificates build-essential procps \
        jq ripgrep zip unzip sqlite3 poppler-utils imagemagick fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 dev
COPY workspace-env.sh /etc/profile.d/workspace.sh
COPY matplotlibrc /etc/matplotlibrc
USER dev
WORKDIR /workspace
CMD ["sleep", "infinity"]
