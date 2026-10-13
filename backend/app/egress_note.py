"""出网被拦 → 说给模型 / 用户的话：唯一入口（v2.37）。

两道关卡各拦各的，说法在这里统一：
- 云浏览器（browser/egress.py）：快照带 blocked → browser 工具结果最前面一句；
- 沙盒电脑（sandbox/egress.py）：前台命令结果带 egress_blocked → run_command / 用户的 `!命令`；
  后台任务（含前台转后台的）被拦的写在工作区 .jobs/<id>/egress（JSON 行）→ jobs.describe 结束时带上。
要点：告诉模型这是被拦、不是网站坏了，别换写法 / 换工具 / 换端口去绕；用户真要连自己内网的机器才提 OUTBOUND_ALLOW_HOSTS；
用户自己设的拒绝名单命中时不提允许名单（那是他的决定）。
"""
import json
from pathlib import Path

SHOW = 3          # 最多列几个地址，其余“等 N 个”
REASON_CHARS = 80
JOB_FILE = "egress"  # 与 sandbox/egress.py JOB_FILE 同名
DENY_MARK = "拒绝名单"  # sandbox/egress.py 拒绝名单命中的原因里都有这四个字

WHERE = {"browser": "页面里有请求被拦下", "command": "这条命令连网时有地址被拦下", "job": "它运行时有连网请求被拦下"}
WHO = {"browser": "助手的浏览器", "command": "助手的电脑", "job": "助手的电脑"}


def items(raw) -> list[dict]:
    """只留像样的 {host, reason}，同一主机一条。"""
    out: dict[str, dict] = {}
    for b in raw or []:
        if isinstance(b, dict) and isinstance(b.get("host"), str) and b["host"]:
            out.setdefault(b["host"], {"host": b["host"], "reason": str(b.get("reason") or b["host"])})
    return list(out.values())


def note(raw, where: str = "command") -> str:
    """给模型的一段（以 ⚠ 开头、换行结尾）；没被拦 → 空串。"""
    got = items(raw)
    if not got:
        return ""
    shown = "；".join(b["reason"][:REASON_CHARS] for b in got[:SHOW])
    more = f"等 {len(got)} 个地址" if len(got) > SHOW else ""
    head = f"⚠ {WHERE.get(where, WHERE['command'])}（{shown}{more}）：{WHO.get(where, WHO['command'])}只能访问公网，"
    if all(DENY_MARK in b["reason"] for b in got):
        return head + "这些地址在用户设的拒绝名单里。这是他的决定，别换地址、换工具或换端口去绕，照实告诉他。\n"
    tail = ("页面缺的部分多半就是它，" if where == "browser" else "失败多半就是因为它，")
    return (head + "内网 / 本机 / 云主机元数据地址一律不许连。" + tail + "别换地址、换工具或换端口去绕；"
            "用户确实要连自己内网的机器，请他把主机加进 OUTBOUND_ALLOW_HOSTS。\n")


def for_user(raw) -> str | None:
    """用户自己跑的 `!命令` 卡片底下的一句；没被拦 → None。"""
    got = items(raw)
    if not got:
        return None
    hosts = "、".join(b["host"] for b in got[:SHOW]) + (f" 等 {len(got)} 个" if len(got) > SHOW else "")
    return f"连 {hosts} 被拦下了：这台电脑只能上公网（要连自己内网的机器，把它加进 OUTBOUND_ALLOW_HOSTS）"


def read_job(job_dir: Path) -> list[dict]:
    """后台任务目录里的 egress 文件（沙盒服务写的 JSON 行）；没有 / 坏行 → 忽略。"""
    try:
        text = (job_dir / JOB_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    raw = []
    for line in text.splitlines()[:50]:
        try:
            raw.append(json.loads(line))
        except ValueError:
            continue
    return items(raw)
