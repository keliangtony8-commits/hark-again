"""结构化提取的唯一规则：从一段原文里按用户给的 JSON Schema 抽出数据，保证交回的是合法、符合 schema 的 JSON。

参照（docs/core-research.md BRAIN as）：
  - Gemini CLI core/baseLlmClient.ts generateJson：cleanJsonResponse 去掉 ```json 围栏、内容不是合法 JSON 就重试
    （DEFAULT_MAX_ATTEMPTS 5）；utils/schemaValidator.ts 用完整的校验器（ajv，strictSchema=false：不认识的关键字忽略，
    $schema 是 2020-12 才换 2020 校验器）。这里同样：jsonschema 库（ajv 的 Python 对应），按 $schema 选草案，默认 draft-07。
  - Codex exec --output-schema：把 schema 交给供应商做严格结构化输出——我们的供应商（阶跃等 OpenAI 兼容接口）不保证支持，
    所以不依赖它，改用“校验 + 把错误逐条喂回去修”（嫁接：Gemini 只在解析失败时盲重试，我们把校验错误告诉模型，修得更准、更省次数）。
  - deepseek-harness：没有。
我们自己的部分：长原文按段落切块（每块一次便宜模型调用，并发 PARALLEL），各块结果按 schema 合并（数组拼接去重、
其它字段取第一个非空值），合并后再整体校验一次；原文超过 SOURCE_MAX 只取前面并注明。

成本：每块 1 次 summary_model（或 EXTRACT_MODEL）调用，校验不过最多再修 ATTEMPTS-1 次；原文 ≤ CHUNK_CHARS 时通常就 1 次。"""
import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError

CHUNK_CHARS = 24000     # 每块原文最多多少字（便宜模型的上下文 + 输出都放得下）
CHUNKS_MAX = 8          # 最多切几块
SOURCE_MAX = CHUNK_CHARS * CHUNKS_MAX
SNAP = 0.2              # 切口往回找空行 / 换行最多退让 20%
ATTEMPTS = 3            # 每块最多问几次（1 次 + 2 次带错误的修正；Gemini 盲重试 5 次）
PARALLEL = 3            # 同时提取几块
ERRORS_MAX = 8          # 喂回模型 / 交给主助手的校验错误最多几条
SCHEMA_MAX = 20000      # schema 本身（JSON 文本）最多多少字
INSTRUCTION_MAX = 2000
OUTPUT_TOKENS = 4096
DRAFT_2020 = "https://json-schema.org/draft/2020-12/schema"

Call = Callable[[list[dict]], Awaitable[str]]


class ExtractError(Exception):
    """没法开始（参数 / schema 有问题）；原因是给模型看的中文。"""


@dataclass
class Result:
    value: object = None
    errors: list[str] = field(default_factory=list)   # 最终结果仍不符合 schema 的地方（空 = 完全符合）
    chunks: int = 1
    failed_chunks: int = 0                            # 几块一次合法 JSON 都没拿到
    attempts: int = 0                                 # 一共调了几次模型
    partial: bool = False                             # 原文超过 SOURCE_MAX，只抽了前面

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.errors


def check_schema(schema) -> Draft7Validator | Draft202012Validator:
    """schema 必须是对象，根类型是 object 或 array（结果才好合并、好落盘）；不合法的 schema 直接拒绝。"""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except ValueError as e:
            raise ExtractError(f"schema 不是合法 JSON：{e}") from e
    if not isinstance(schema, dict):
        raise ExtractError("schema 要是一个 JSON 对象，比如 {\"type\":\"object\",\"properties\":{…}}。")
    if len(json.dumps(schema, ensure_ascii=False)) > SCHEMA_MAX:
        raise ExtractError(f"schema 太大（超过 {SCHEMA_MAX} 字），精简一下字段。")
    root = schema.get("type")
    if root not in ("object", "array"):
        raise ExtractError("schema 的根 type 要是 object 或 array（要一组数据就用 array，单条用 object）。")
    cls = Draft202012Validator if schema.get("$schema") == DRAFT_2020 else Draft7Validator
    try:
        cls.check_schema(schema)
    except SchemaError as e:
        raise ExtractError(f"schema 不合法：{e.message}") from e
    return cls(schema)


_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)


def clean(text: str) -> str:
    """Gemini cleanJsonResponse：去掉 ```json 围栏；嫁接：围栏不在开头、前后有闲话时，取第一个 { / [ 到最后一个 } / ]。"""
    t = (text or "").strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    if t[:1] not in ("{", "["):
        starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
        if starts:
            t = t[min(starts):]
    end = max(t.rfind("}"), t.rfind("]"))
    return t[:end + 1] if end >= 0 else t


def parse(text: str) -> tuple[object, str]:
    """(值, 错误)。值为 None 时错误说明为什么。"""
    t = clean(text)
    if not t:
        return None, "回复是空的"
    try:
        return json.loads(t), ""
    except ValueError as e:
        return None, f"不是合法 JSON（{e.msg}，第 {e.lineno} 行第 {e.colno} 列）"


def _path(parts) -> str:
    out = "$"
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def errors(validator, value) -> list[str]:
    """校验错误，按路径排序，最多 ERRORS_MAX 条：“$.items[2].price：'12元' is not of type 'number'”。"""
    found = sorted(validator.iter_errors(value), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    out = [f"{_path(e.absolute_path)}：{e.message[:200]}" for e in found[:ERRORS_MAX]]
    if len(found) > ERRORS_MAX:
        out.append(f"……还有 {len(found) - ERRORS_MAX} 处")
    return out


def split(text: str) -> tuple[list[str], bool]:
    """(块, 是否超过 SOURCE_MAX 被截)。切口优先落在空行，其次换行，往回最多退 SNAP。"""
    partial = len(text) > SOURCE_MAX
    text = text[:SOURCE_MAX]
    out, start = [], 0
    while start < len(text):
        end = start + CHUNK_CHARS
        if end >= len(text):
            out.append(text[start:])
            break
        floor = end - int(CHUNK_CHARS * SNAP)
        cut = text.rfind("\n\n", floor, end - 1)
        if cut >= 0:
            end = cut + 2
        elif (cut := text.rfind("\n", floor, end)) >= 0:
            end = cut + 1
        out.append(text[start:end])
        start = end
    return [c for c in out if c.strip()] or [""], partial


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _concat(lists: list[list]) -> list:
    seen, out = set(), []
    for items in lists:
        for it in items:
            key = json.dumps(it, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(it)
    return out


def merge(values: list, schema: dict):
    """各块结果合成一个：根是数组 → 拼接去重；根是对象 → 数组字段拼接去重，其它字段取第一个非空值。只有一块原样返回。"""
    values = [v for v in values if v is not None]
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if schema.get("type") == "array":
        return _concat([v if isinstance(v, list) else [v] for v in values])
    dicts = [v for v in values if isinstance(v, dict)]
    if not dicts:
        return values[0]
    out: dict = {}
    for d in dicts:
        for k, v in d.items():
            if isinstance(v, list) and isinstance(out.get(k), list):
                out[k] = _concat([out[k], v])
            elif k not in out or (_empty(out[k]) and not _empty(v)):
                out[k] = v
    return out


SYSTEM = """你是数据提取器：只从<原文>里抽取信息，按给定的 JSON Schema 输出。
规则：
1. 只输出一个 JSON 值（对象或数组），不要解释、不要 ``` 围栏。
2. 原文里没有的信息不要编：可选字段省略，schema 允许 null 的填 null。
3. 数字字段输出数字（去掉单位和千分位），日期按 schema 的说明或 YYYY-MM-DD。
4. 原文只是全文的一部分时，只抽这一部分里有的；一条都没有就按 schema 输出空数组 / 空对象。"""


def messages(instruction: str, schema: dict, chunk: str, index: int, total: int) -> list[dict]:
    part = f"（全文切成 {total} 段，这是第 {index + 1} 段）" if total > 1 else ""
    user = (f"要提取什么：{instruction}\n\nJSON Schema：\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"<原文>{part}\n{chunk}\n</原文>")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def repair(raw: str, problems: list[str]) -> list[dict]:
    """把上一次的输出和问题告诉模型，让它改（追加在原对话后面）。"""
    return [{"role": "assistant", "content": raw[:CHUNK_CHARS]},
            {"role": "user", "content": "上面的输出不符合要求：\n- " + "\n- ".join(problems)
             + "\n只改这些问题，重新输出完整的 JSON，不要别的文字。"}]


async def _one(call: Call, validator, base: list[dict]) -> tuple[object, list[str], int]:
    """一块：(值或 None, 剩余错误, 调用次数)。解析失败或校验不过就带着错误再问，最多 ATTEMPTS 次；保留错误最少的那次。"""
    msgs, best, best_err, n = list(base), None, ["一次合法 JSON 都没拿到"], 0
    for _ in range(ATTEMPTS):
        n += 1
        raw = await call(msgs)
        value, err = parse(raw)
        problems = [err] if value is None else errors(validator, value)
        if value is not None and (best is None or len(problems) < len(best_err)):
            best, best_err = value, problems
        if value is not None and not problems:
            return value, [], n
        msgs = [*base, *repair(raw, problems)]
    return best, best_err if best is not None else ["一次合法 JSON 都没拿到"], n


async def run(source: str, instruction: str, schema, call: Call) -> Result:
    """按块提取 → 合并 → 整体校验。schema 可以是 dict 或 JSON 字符串；call(messages) → 模型的文字回复。"""
    instruction = (instruction or "").strip()
    if not instruction:
        raise ExtractError("instruction 不能为空：说清楚要抽哪些信息。")
    if len(instruction) > INSTRUCTION_MAX:
        raise ExtractError(f"instruction 太长（超过 {INSTRUCTION_MAX} 字）。")
    validator = check_schema(schema)
    schema = validator.schema
    if not (source or "").strip():
        raise ExtractError("原文是空的，没有可提取的内容。")
    chunks, partial = split(source)
    sem = asyncio.Semaphore(PARALLEL)

    async def job(i: int, c: str):
        async with sem:
            return await _one(call, validator, messages(instruction, schema, c, i, len(chunks)))

    outs = await asyncio.gather(*(job(i, c) for i, c in enumerate(chunks)))
    res = Result(chunks=len(chunks), partial=partial, attempts=sum(o[2] for o in outs),
                 failed_chunks=sum(1 for o in outs if o[0] is None))
    res.value = merge([o[0] for o in outs], schema)
    if res.value is None:
        res.errors = outs[0][1][:ERRORS_MAX]
    else:
        res.errors = errors(validator, res.value)
    return res


def count(value) -> int | None:
    """结果里有几条：根是数组 → 长度；对象里只有一个数组字段 → 那个数组的长度；否则 None。"""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        if len(lists) == 1:
            return len(lists[0])
    return None


def detail(res: Result, source: str) -> str:
    """时间线上的一行：“网页 · 12 条 · 2 段”。"""
    parts = [source]
    if (n := count(res.value)) is not None:
        parts.append(f"{n} 条")
    if res.chunks > 1:
        parts.append(f"{res.chunks} 段")
    if res.errors:
        parts.append("有不符合处")
    return " · ".join(parts)


def for_model(res: Result) -> str:
    """交给主助手：先说结论（是否完全符合、有没有截断），再给紧凑 JSON（太长由工具结果总闸落盘）。"""
    head = []
    if res.value is None:
        return "没提取成：模型一直没给出合法 JSON。" + ("\n" + "\n".join(res.errors) if res.errors else "")
    if res.errors:
        head.append("提取结果还有不符合 schema 的地方（已尽量修过，下面照实给出，用之前自己核对）：\n- " + "\n- ".join(res.errors))
    else:
        head.append("已提取，结果符合 schema。")
    if res.failed_chunks:
        head.append(f"（{res.chunks} 段里有 {res.failed_chunks} 段没抽出来，结果可能不全）")
    if res.partial:
        head.append(f"（原文超过 {SOURCE_MAX} 字，只抽了前面这部分）")
    return "\n".join(head) + "\n" + json.dumps(res.value, ensure_ascii=False)
