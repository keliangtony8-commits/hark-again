# 工作区环境（装进镜像的 /etc/profile.d/workspace.sh；所有命令都走 bash -l，所以每条都会读到）。
#
# 目的：装的东西留得住。容器随时可能被删掉重建（换镜像、宿主机重启、手动清理），
# 只有挂载进来的工作区目录是持久的，所以“家”也放进工作区：
#   HOME = <工作区>/.home（隐藏目录，文件列表/打包不显示；规则见 backend/app/storage.py HIDDEN_DIRS）
#   pip install（系统 site-packages 不可写 → 自动装到用户目录）→ ~/.local/lib/python3.x/site-packages
#   npm i -g → NPM_CONFIG_PREFIX=~/.local（命令在 ~/.local/bin，已在 PATH 最前面）
#   git config --global、ssh known_hosts 也都留得住；自己的环境变量写进 ~/.profile（bash -l 读完这里接着读它）
# 缓存（pip / npm / 其他 XDG 缓存）放 /tmp：可再生，不该吃工作区磁盘。
# 在虚拟环境里（python -m venv .venv && . .venv/bin/activate）pip 照常装进 .venv——它本来就在工作区。
# 后端那一侧的说明（给模型的话）在 backend/app/workspaces.py ENVIRONMENT，改这里要同步改那里。

WORKSPACE="${WORKSPACE:-/workspace}"
if [ -d "$WORKSPACE" ] && [ -w "$WORKSPACE" ]; then
    export HOME="$WORKSPACE/.home"
    mkdir -p "$HOME/.local/bin" 2>/dev/null
    export PYTHONUSERBASE="$HOME/.local"
    export NPM_CONFIG_PREFIX="$HOME/.local"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) export PATH="$HOME/.local/bin:$PATH" ;;
    esac
    export XDG_CACHE_HOME="/tmp/.cache"
    export NPM_CONFIG_CACHE="/tmp/.npm"
    export PIP_DISABLE_PIP_VERSION_CHECK=1
fi
