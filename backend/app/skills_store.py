"""技能库：一个技能 = 一个 Markdown 文件。
格式：首行 `# 名称`，第二段为一句话描述，其余为正文（做法步骤）。
内置技能在 app/skills/（只读），用户技能在 data/skills/（可增删改）。
用户目录里与内置同 id 的文件 = “自定义版”：它顶替内置那条（目录里只出现一次，模型只看到一份），
customized=True；删掉它就恢复内置（reset）。新建技能的 id 避开所有已存在的 id，绝不意外覆盖或顶替。
停用：data/skills/_disabled.json 记一组 id（按 id 记，与内置/自定义无关，恢复默认不丢开关）。
停用的技能留在目录里给用户看（enabled=False），但不进模型的技能目录、use_skill 读不到。"""
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .storage import SKILLS, safe_join

BUILTIN = Path(__file__).resolve().parent / "skills"


@dataclass
class Skill:
    id: str
    name: str
    description: str
    body: str
    builtin: bool
    customized: bool = False
    enabled: bool = True

    def dict(self) -> dict:
        return asdict(self)


def _parse(p: Path, builtin: bool) -> Skill:
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    name = lines[0].lstrip("# ").strip() if lines else p.stem
    rest = [l for l in lines[1:]]
    desc_i = next((i for i, l in enumerate(rest) if l.strip()), None)
    desc = rest[desc_i].strip() if desc_i is not None else ""
    body = "\n".join(rest[desc_i + 1:]).strip() if desc_i is not None else ""
    return Skill(p.stem, name, desc, body, builtin)


def _builtin_path(sid: str) -> Path | None:
    if not sid or "/" in sid or "\\" in sid or sid.startswith("."):
        return None
    p = BUILTIN / f"{sid}.md"
    return p if p.is_file() else None


DISABLED = "_disabled.json"


def _disabled() -> set[str]:
    p = SKILLS / DISABLED
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("disabled", []))
    except (OSError, ValueError, AttributeError):
        return set()


def _write_disabled(ids: set[str]) -> None:
    SKILLS.mkdir(parents=True, exist_ok=True)
    (SKILLS / DISABLED).write_text(json.dumps({"disabled": sorted(ids)}, ensure_ascii=False), encoding="utf-8")


def list_skills() -> list[Skill]:
    """内置在前（自定义版就地顶替，保持位置），用户自己的在后。含停用的（enabled=False）。"""
    out = {p.stem: _parse(p, True) for p in sorted(BUILTIN.glob("*.md"))}
    mine: list[Skill] = []
    if SKILLS.is_dir():
        for p in sorted(SKILLS.glob("*.md")):
            s = _parse(p, False)
            if s.id in out:
                s.customized = True
                out[s.id] = s
            else:
                mine.append(s)
    off = _disabled()
    allv = [*out.values(), *mine]
    for s in allv:
        s.enabled = s.id not in off
    return allv


def enabled_skills() -> list[Skill]:
    """模型能看到、能用的技能。"""
    return [s for s in list_skills() if s.enabled]


def get_skill(sid: str) -> Skill | None:
    return next((s for s in list_skills() if s.id == sid), None)


def set_enabled(sid: str, on: bool) -> Skill:
    if get_skill(sid) is None:
        raise KeyError(sid)
    off = _disabled()
    (off.discard if on else off.add)(sid)
    _write_disabled(off)
    return get_skill(sid)  # type: ignore[return-value]


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip().lower()).strip("-")
    return s or "skill"


def _unique_id(name: str) -> str:
    taken = {s.id for s in list_skills()}
    base = _slug(name)
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


def _write(sid: str, name: str, description: str, body: str) -> Skill:
    SKILLS.mkdir(parents=True, exist_ok=True)
    safe_join(SKILLS, f"{sid}.md").write_text(f"# {name}\n{description}\n\n{body}\n", encoding="utf-8")
    return get_skill(sid)  # type: ignore[return-value]


def save_skill(name: str, description: str, body: str, sid: str | None = None) -> Skill:
    """sid=None 新建（id 唯一）；给 sid 则整体替换已有的用户技能或自定义版。"""
    if sid is None:
        return _write(_unique_id(name), name, description, body)
    cur = get_skill(sid)
    if cur is None:
        raise KeyError(sid)
    if cur.builtin:
        raise ValueError("内置技能不能直接修改，先复制一份来改")
    return _write(sid, name, description, body)


def edit_skill(sid: str, find: str, replace: str) -> Skill:
    """在技能全文（名称行 + 描述 + 正文）里把唯一一处 find 换成 replace（v2.46，学 Hark skill edit）。
    内置技能先复制成自定义版再改。find 为空 / 找不到 / 不止一处 → ValueError（中文原因，给模型看）。
    改完名称行必须还在（首行 `# 名称`），否则拒绝。"""
    cur = get_skill(sid)
    if cur is None:
        raise KeyError(sid)
    if not find:
        raise ValueError("find 不能为空：写出要替换的原文（带上前后几个字让它唯一）。")
    text = f"# {cur.name}\n{cur.description}\n\n{cur.body}\n"
    n = text.count(find)
    if n == 0:
        raise ValueError("技能里没有这段原文（要逐字一致，含标点和换行）；先 use_skill 看当前全文再改。")
    if n > 1:
        raise ValueError(f"这段原文在技能里出现了 {n} 次，多带点上下文让它只出现一次。")
    new = text.replace(find, replace, 1)
    if not new.lstrip().startswith("# ") or not new.lstrip()[2:].split("\n", 1)[0].strip():
        raise ValueError("改完首行必须还是 `# 技能名称`。")
    if cur.builtin:
        customize(sid)
    SKILLS.mkdir(parents=True, exist_ok=True)
    safe_join(SKILLS, f"{sid}.md").write_text(new.strip() + "\n", encoding="utf-8")
    return get_skill(sid)  # type: ignore[return-value]


def customize(sid: str) -> Skill:
    """把内置技能复制成自定义版（已经有了就原样返回）。"""
    src = _builtin_path(sid)
    if src is None:
        raise KeyError(sid)
    dst = safe_join(SKILLS, f"{sid}.md")
    if not dst.exists():
        SKILLS.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return get_skill(sid)  # type: ignore[return-value]


def reset(sid: str) -> Skill:
    """丢掉自定义版，回到内置原样。"""
    if _builtin_path(sid) is None:
        raise KeyError(sid)
    p = safe_join(SKILLS, f"{sid}.md")
    if p.exists():
        p.unlink()
    return get_skill(sid)  # type: ignore[return-value]


def delete_skill(sid: str) -> None:
    """只删用户自己的技能；内置不能删，自定义版走 reset。"""
    if _builtin_path(sid) is not None:
        raise ValueError("内置技能不能删除；自定义过的可以恢复默认")
    p = safe_join(SKILLS, f"{sid}.md")
    if not p.exists():
        raise KeyError(sid)
    p.unlink()
    if sid in (off := _disabled()):  # 以后新建同 id 的技能不该继承旧开关
        off.discard(sid)
        _write_disabled(off)
