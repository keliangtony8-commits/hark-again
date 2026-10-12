"""云浏览器和工作区之间搬文件的唯一规则（v1.32，对标 Hark“浏览器任务能把工作区文件传到网页上”、Manus 云浏览器下载的文件进沙盒）。

浏览器服务（browser/service.py）和沙盒是两个容器，互相看不到文件，后端在中间搬：
- 上传 upload(ws, session, ref, paths)：路径必须是工作区里真实存在的普通文件（storage.project_file：越界、目录、
  .git/.jobs/.spill/.home 里的都不行——家目录里可能有密钥配置，不能被传到第三方网站）；最多 MAX_UPLOAD_FILES 个，
  总共 UPLOAD_MAX_MB；后端读出来 base64 交给浏览器服务放进文件框。只是“放进框里”，真正提交还要点按钮（提交/发送/发布类按钮照旧审批）。
- 下载 collect(ws, session)：页面触发的下载先落在浏览器服务的中转目录；每次浏览器动作之后后端取走，存进工作区
  DOWNLOAD_DIR/（同名不覆盖：报告.pdf → 报告 (2).pdf），先过磁盘配额（quota.check），放不下就丢掉并说明；
  取走或丢掉都让服务端删中转文件。还在下的留到下一次动作再取。
- 卡片：每搬一个文件，浏览器画面卡的 files 里记一条 {kind upload|download, name, path}，卡上 workspace = 工作区 id
  （客户端点了用工作区文件接口打开）。同一条回复里同会话的卡由 loop.MessageBuilder 合并 files（carry）。
返回 Moved(note, files)：note 给模型，files 给卡片；出错抛 BrowserFileError（中文原因）。
"""
import asyncio
import base64
from dataclasses import dataclass, field
from pathlib import Path

from . import browser_client, quota, storage

DOWNLOAD_DIR = "downloads"
MAX_UPLOAD_FILES = 5
UPLOAD_MAX_MB = 20  # 与 browser/service.py UPLOAD_MAX 同值
CARD_FILES_MAX = 8  # 一张画面卡最多列几条（最近的）


class BrowserFileError(RuntimeError):
    pass


@dataclass
class Moved:
    note: str = ""
    files: list[dict] = field(default_factory=list)


def resolve(ws: str, paths: list[str]) -> list[tuple[str, Path]]:
    """要上传的工作区文件 → [(相对路径, 绝对路径)]；任何一个不行就整体拒绝（别传一半）。"""
    clean = [p.strip().lstrip("/") for p in paths if p and p.strip()]
    if not clean:
        raise BrowserFileError("没给要上传的文件路径。")
    if len(clean) > MAX_UPLOAD_FILES:
        raise BrowserFileError(f"一次最多传 {MAX_UPLOAD_FILES} 个文件。")
    out, total = [], 0
    for rel in clean:
        rel = rel.removeprefix("workspace/")
        p = storage.project_file(ws, rel)
        if p is None:
            raise BrowserFileError(f"工作区里没有文件 {rel}（目录要先打包成 zip；隐藏目录里的文件不能传到网页）。")
        size = p.stat().st_size
        if size == 0:
            raise BrowserFileError(f"{rel} 是空文件。")
        total += size
        if total > UPLOAD_MAX_MB * 1024 * 1024:
            raise BrowserFileError(f"一次最多传 {UPLOAD_MAX_MB} MB，{rel} 放不下了；分几次传或先压缩。")
        out.append((rel, p))
    return out


async def upload(ws: str, session: str, ref: str, paths: list[str]) -> tuple[dict, Moved]:
    """→ (浏览器服务返回的新快照, Moved)。"""
    files = await asyncio.to_thread(resolve, ws, paths)
    payload = [{"name": p.name, "mime": storage.mime_of(p.name),
                "data": base64.b64encode(await asyncio.to_thread(p.read_bytes)).decode()} for _, p in files]
    snap = await browser_client.snapshot_call(session, "POST", "/upload", {"ref": ref, "files": payload})
    names = "、".join(rel for rel, _ in files)
    return snap, Moved(f"已把 {names} 放进网页的文件框（还没提交；需要的话再点提交/上传按钮）。",
                       [{"kind": "upload", "name": p.name, "path": rel} for rel, p in files])


def _free_name(folder: Path, name: str) -> Path:
    base = Path(name).name.strip() or "download"
    dst = folder / base
    stem, suf = Path(base).stem, Path(base).suffix
    n = 2
    while dst.exists():
        dst = folder / f"{stem} ({n}){suf}"
        n += 1
    return dst


async def collect(ws: str, session: str) -> Moved:
    """把浏览器服务里攒下的下载搬进工作区 downloads/。浏览器服务连不上/没这个会话 → 空结果，不打断动作本身。"""
    try:
        items = await browser_client.downloads(session)
    except Exception:
        return Moved()
    moved, notes, waiting = [], [], 0
    folder = storage.project_dir(ws) / DOWNLOAD_DIR
    for d in items:
        if d.get("state") == "downloading":
            waiting += 1
            continue
        try:
            if d.get("state") != "done":
                notes.append(f"{d.get('name')}：{d.get('error') or '下载失败'}")
                continue
            try:
                await asyncio.to_thread(quota.check, ws, int(d.get("size") or 0))
            except quota.QuotaError as e:
                notes.append(f"{d.get('name')} 没存：{e}")
                continue
            folder.mkdir(parents=True, exist_ok=True)
            dst = await asyncio.to_thread(_free_name, folder, str(d.get("name") or "download"))
            try:
                await browser_client.fetch_download(session, d["id"], dst)
            except Exception as e:
                dst.unlink(missing_ok=True)
                notes.append(f"{d.get('name')} 没取到：{e}")
                continue
            rel = f"{DOWNLOAD_DIR}/{dst.name}"
            moved.append({"kind": "download", "name": dst.name, "path": rel})
            notes.append(f"已存到工作区 {rel}（{quota.size_text(dst.stat().st_size)}）")
        finally:
            if d.get("state") != "downloading":
                try:
                    await browser_client.drop_download(session, d["id"])
                except Exception:
                    pass
    if moved:
        quota.forget(ws)
    if waiting:
        notes.append(f"还有 {waiting} 个文件在下载，过一会儿用 browser_read 再看")
    if not notes:
        return Moved()
    return Moved("网页下载了文件：" + "；".join(notes) + "。要给用户就用 display_file。", moved)


def card_files(old: list | None, new: list | None) -> list[dict]:
    """卡片上的文件清单：旧的在前、新的在后，同一 (kind, path) 只留一条，最多 CARD_FILES_MAX 条（留最近的）。"""
    out: list[dict] = []
    for f in [*(old or []), *(new or [])]:
        if not isinstance(f, dict):
            continue
        out = [x for x in out if (x.get("kind"), x.get("path")) != (f.get("kind"), f.get("path"))]
        out.append(f)
    return out[-CARD_FILES_MAX:]
