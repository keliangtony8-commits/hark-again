"""整台服务器的读数（v2.85）——“我的 → 我的电脑”里“整台服务器”那一行的唯一来源。
用户 2026-10-14 16:03：页面上是他那块沙盒（512 MB / 3 GB），对不上 VPS 面板的 4 GB；所以两者都写清，整机单独一行。
后端容器读 /proc/meminfo、loadavg 和数据盘的 statvfs：没有 lxcfs 时容器里看到的就是宿主机（Docker 默认如此），
数据盘就是 VPS 的盘。读不到（非 Linux、权限）→ 对应字段 None，前端少说那一段，不报错。
只在个人工作区的电脑状态里给：整机不属于某个项目。没有多用户，自建服务器的唯一用户就是管理员。
"""
import os
from pathlib import Path

MEMINFO = Path("/proc/meminfo")


def _meminfo(text: str) -> tuple[int | None, int | None]:
    vals: dict[str, int] = {}
    for line in text.splitlines():
        k, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            vals[k.strip()] = int(parts[0]) * 1024  # 单位 kB
    total = vals.get("MemTotal")
    avail = vals.get("MemAvailable", vals.get("MemFree"))
    return total, (total - avail if total is not None and avail is not None else None)


def read(data_dir: str) -> dict:
    """{cpus, load1, memory_total, memory_used, disk_total, disk_used}：字节；读不到的为 None。"""
    try:
        mem_total, mem_used = _meminfo(MEMINFO.read_text())
    except OSError:
        mem_total = mem_used = None
    try:
        load1 = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load1 = None
    try:
        st = os.statvfs(data_dir)
        disk_total, disk_used = st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bfree) * st.f_frsize
    except OSError:
        disk_total = disk_used = None
    return {"cpus": os.cpu_count(), "load1": load1, "memory_total": mem_total, "memory_used": mem_used,
            "disk_total": disk_total, "disk_used": disk_used}
