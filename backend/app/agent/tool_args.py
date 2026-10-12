# SPDX-License-Identifier: MIT
# Ported from deepseek-harness/packages/core/tools/src/json-schema.ts (validateJsonSchemaValue / checkValue)
# and packages/core/tools/src/schema.ts (validateArgs) (MIT), modified:
#   - Python, recursive with a depth cap (our tool schemas are a few levels deep, not hostile);
#   - lenient like Gemini CLI utils/schemaValidator.ts (Apache-2.0, modified): unknown keywords are ignored,
#     so MCP schemas never block a call;
#   - grafts: type lists, anyOf/allOf, minimum/maximum, minItems/maxItems, minLength/maxLength;
#   - repair layer (ours): fenced / trailing-text / double-encoded JSON, safe scalar coercions;
#   - tool-name suggestion ported from Gemini CLI utils/tool-utils.ts getToolSuggestion (Apache-2.0, modified).
"""工具调用参数的唯一规则：模型给的参数先过这里，再进审批、再执行。

parse(raw, cut)：参数字符串 → 对象。坏 JSON 先做几种确定性的小修（去 ```json 围栏、截掉对象后面的多余文字、
  被二次编码成字符串的 JSON），修不好就给模型一句带位置的原因（Codex：failed to parse function arguments: <serde 原因>）；
  输出被长度上限截断（cut）时直说“参数被截断”，让模型拆小。
check(schema, args, accepts)：安全的类型修正（"5"→5、"true"→true、5.0→5）→ 校验（deepseek checkValue 的规则与顺序：
  必填、类型、enum/const、oneOf 恰好一个、additionalProperties:false）→ 丢掉函数收不下的未知参数并告诉模型。
  有违规就整次不执行，把逐条原因（带路径）还给模型改。
suggest(name, names)：工具名写错时给最像的三个（Gemini Did you mean）。
wire(parsed)：写回给模型的历史里的参数——坏 JSON 不能原样回传（有的供应商下一轮直接 400）。
"""
import json
import re
from dataclasses import dataclass, field

MAX_DEPTH = 32       # 再深就不往下查（只查到这里也不算错）
VIOLATIONS_MAX = 8   # 给模型看的违规条数上限，多了只说“还有 N 处”
SUGGEST_MAX = 3      # Gemini topN = 3
SUGGEST_DISTANCE = 0.5  # 编辑距离超过名字长度的一半就不算“像”（ours：免得给出风马牛的建议）

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.S)
_INT = re.compile(r"^[+-]?\d+$")
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


@dataclass
class Parsed:
    args: dict | None          # None = 解析失败
    error: str = ""            # 给模型看的原因
    repaired: str = ""         # 做了哪种修补（空 = 原样就是合法 JSON）
    notes: list[str] = field(default_factory=list)  # 执行时附在工具结果后面的提醒（丢掉的未知参数等）


def _loads(text: str):
    return json.loads(text)


def parse(raw: str | None, cut: bool = False) -> Parsed:
    """参数字符串 → Parsed。空串 = {}（不少供应商无参调用给空串）。"""
    text = (raw or "").strip()
    if not text:
        return Parsed({})
    first_error = None
    try:
        value = _loads(text)
        return _object(value, "")
    except json.JSONDecodeError as e:
        first_error = e
    if cut:
        return Parsed(None, "参数被输出长度上限截断了，JSON 不完整。内容太长就拆开：先写一部分，再用 edit_file 或分几次追加。")
    # 1) ```json … ``` 围栏
    if m := _FENCE.match(text):
        try:
            return _object(_loads(m.group(1).strip()), "去掉了代码围栏")
        except json.JSONDecodeError:
            pass
    # 2) 合法对象后面跟了多余文字（"{…} 好的" / 两个对象连写取第一个）
    if text.startswith("{"):
        try:
            value, end = json.JSONDecoder().raw_decode(text)
            if isinstance(value, dict) and text[end:].strip():
                return _object(value, "去掉了 JSON 后面多余的文字")
        except json.JSONDecodeError:
            pass
    e = first_error
    at = f"第 {e.lineno} 行第 {e.colno} 列" if e.lineno > 1 else f"第 {e.pos + 1} 个字符"
    ends = e.pos >= len(text) - 1 or e.msg.startswith("Unterminated string")  # 到结尾都没收住 = 像是断了
    tail = "（看起来在结尾处断了，可能是内容太长被截断）" if ends else ""
    return Parsed(None, f"参数不是合法 JSON：{at}附近 {_why(e.msg)}{tail}。请改好再调用。")


def _why(msg: str) -> str:
    table = {
        "Expecting value": "缺少值",
        "Expecting property name enclosed in double quotes": "属性名要用双引号",
        "Expecting ',' delimiter": "缺少逗号",
        "Expecting ':' delimiter": "缺少冒号",
        "Unterminated string starting at": "字符串没有结束引号",
        "Invalid control character at": "字符串里有未转义的控制字符（换行要写成 \\n）",
        "Invalid \\escape": "无效的转义",
        "Extra data": "后面还有多余内容",
    }
    for k, v in table.items():
        if msg.startswith(k):
            return v
    return msg


def _object(value, repaired: str) -> Parsed:
    # 被二次编码："{\"path\": \"a\"}" → 再解一次（常见于小模型）
    if isinstance(value, str):
        inner = value.strip()
        if inner.startswith("{"):
            try:
                again = json.loads(inner)
                if isinstance(again, dict):
                    return Parsed(again, repaired="参数被编码成了字符串，已解开")
            except json.JSONDecodeError:
                pass
    if not isinstance(value, dict):
        return Parsed(None, "参数要是一个 JSON 对象（{…}），请改好再调用。")
    return Parsed(value, repaired=repaired)


# —— 校验（deepseek checkValue 的规则；路径写法 a.b[0]，根 = arguments） ——

def _path(path: str) -> str:
    return path or "arguments"


def _prop(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _types(node: dict) -> list[str] | None:
    t = node.get("type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list) and all(isinstance(x, str) for x in t):
        return t
    return None


def _is(kind: str, v) -> bool:
    if kind == "string":
        return isinstance(v, str)
    if kind == "boolean":
        return isinstance(v, bool)
    if kind == "integer":
        return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer())
    if kind == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))
    if kind == "null":
        return v is None
    if kind == "array":
        return isinstance(v, list)
    if kind == "object":
        return isinstance(v, dict)
    return True  # 不认识的类型名：宽松放过（Gemini：编不了的 schema 就跳过校验）


_KIND = {"string": "字符串", "integer": "整数", "number": "数字", "boolean": "布尔值（true/false）",
         "null": "null", "array": "数组", "object": "对象"}


def validate(schema, value, path: str = "", depth: int = 0, strict: bool = True) -> list[str]:
    """违规清单（按遍历顺序，带路径）；空 = 合法。schema 不是对象 / 太深 = 不查。
    strict=False（执行前用）只查“结构”：必填、类型、oneOf/anyOf、additionalProperties:false——这些错了 Python 代码会崩；
    enum/const、长度/条数/大小这些“软约束”交给工具自己收拾（超出的截掉、不认识的种类回落），省一次来回。"""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return []
    out: list[str] = []
    if isinstance(schema.get("oneOf"), list):  # deepseek：恰好匹配一个
        n = sum(1 for b in schema["oneOf"] if not validate(b, value, path, depth + 1, strict))
        if n != 1:
            return [f"“{_path(path)}”要恰好符合 oneOf 里的一种写法（现在符合 {n} 种）"]
    if isinstance(schema.get("anyOf"), list) and schema["anyOf"]:
        if not any(not validate(b, value, path, depth + 1, strict) for b in schema["anyOf"]):
            return [f"“{_path(path)}”不符合 anyOf 里的任何一种写法"]
    if isinstance(schema.get("allOf"), list):
        for b in schema["allOf"]:
            out += validate(b, value, path, depth + 1, strict)
    kinds = _types(schema)
    if kinds is not None and not any(_is(k, value) for k in kinds):
        want = "或".join(_KIND.get(k, k) for k in kinds)
        return out + [f"“{_path(path)}”应为{want}"]
    if strict and "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
        return out + [f"“{_path(path)}”只能是 {json.dumps(schema['enum'], ensure_ascii=False)} 之一"]
    if strict and "const" in schema and value != schema["const"]:
        return out + [f"“{_path(path)}”必须是 {json.dumps(schema['const'], ensure_ascii=False)}"]
    if strict and isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(schema.get("minimum"), (int, float)) and value < schema["minimum"]:
            out.append(f"“{_path(path)}”不能小于 {schema['minimum']}")
        if isinstance(schema.get("maximum"), (int, float)) and value > schema["maximum"]:
            out.append(f"“{_path(path)}”不能大于 {schema['maximum']}")
    if strict and isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            out.append(f"“{_path(path)}”至少 {schema['minLength']} 个字")
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            out.append(f"“{_path(path)}”最多 {schema['maxLength']} 个字")
    if isinstance(value, dict):
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema["required"] if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in value or (value[key] is None and not _nullable(props.get(key))):
                out.append(f"缺少必填参数“{_prop(path, key)}”")
        for key, child in props.items():
            if key in value and value[key] is not None:  # null：必填的上面已报缺，可选的当没给
                out += validate(child, value[key], _prop(path, key), depth + 1, strict)
        if schema.get("additionalProperties") is False:
            out += [f"“{_prop(path, k)}”不是可用的参数" for k in value if k not in props]
    if isinstance(value, list):
        if strict and isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            out.append(f"“{_path(path)}”至少要 {schema['minItems']} 项")
        if strict and isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            out.append(f"“{_path(path)}”最多 {schema['maxItems']} 项")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out += validate(schema["items"], item, f"{_path(path)}[{i}]", depth + 1, strict)
    return out


def _nullable(node) -> bool:
    kinds = _types(node) if isinstance(node, dict) else None
    return bool(kinds and "null" in kinds)


# —— 安全的类型修正（ours：便宜模型常把数字、布尔写成字符串；只改一眼就确定的） ——

def coerce(schema, value, depth: int = 0):
    """按 schema 修正明显的写法错误，返回 (新值, 改了几处)。不确定的一律不动，交给 validate 报错。"""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return value, 0
    kinds = _types(schema) or []
    if isinstance(value, str) and "string" not in kinds:
        s = value.strip()
        if "integer" in kinds and _INT.match(s):
            return int(s), 1
        if "number" in kinds and _NUM.match(s):
            n = float(s)
            return (int(n) if n.is_integer() and "." not in s and "e" not in s.lower() else n), 1
        if "boolean" in kinds and s.lower() in ("true", "false"):
            return s.lower() == "true", 1
        if ("array" in kinds or "object" in kinds) and s[:1] in "[{":  # 数组/对象被写成了 JSON 字符串
            try:
                inner = json.loads(s)
            except json.JSONDecodeError:
                return value, 0
            if ("array" in kinds and isinstance(inner, list)) or ("object" in kinds and isinstance(inner, dict)):
                fixed, n = coerce(schema, inner, depth + 1)
                return fixed, n + 1
        return value, 0
    if isinstance(value, float) and value.is_integer() and "integer" in kinds and "number" not in kinds:
        return int(value), 1
    if isinstance(value, dict):
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        total, out = 0, dict(value)
        for k, child in props.items():
            if k in out:
                out[k], n = coerce(child, out[k], depth + 1)
                total += n
        return out, total
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        total, out = 0, []
        for item in value:
            fixed, n = coerce(schema["items"], item, depth + 1)
            out.append(fixed)
            total += n
        return out, total
    return value, 0


@dataclass
class Checked:
    args: dict
    error: str = ""                       # 非空 = 不执行，把它还给模型
    notes: list[str] = field(default_factory=list)


def check(schema: dict, args: dict, accepts: set[str] | None = None) -> Checked:
    """修正 → 校验 → 丢掉函数收不下的未知参数。accepts = 工具函数能收的参数名（None = 全收，如带 **kwargs）。"""
    fixed, n = coerce(schema, args)
    notes = []
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    for k in [k for k, v in fixed.items() if v is None and k not in required and not _nullable(props.get(k))]:
        fixed.pop(k)  # 可选参数给了 null = 没给（让函数用默认值；deepseek：present undefined 按缺失处理）
    if accepts is not None:
        unknown = [k for k in fixed if k not in accepts]
        if unknown:
            for k in unknown:
                fixed.pop(k)
            notes.append(f"忽略了不认识的参数：{'、'.join(unknown)}")
    violations = validate(schema, fixed, strict=False)
    if violations:
        shown = violations[:VIOLATIONS_MAX]
        more = f"；还有 {len(violations) - len(shown)} 处" if len(violations) > len(shown) else ""
        return Checked(fixed, "参数不对：" + "；".join(shown) + more + "。请按这个工具的参数说明改好再调用。", notes)
    if n:
        notes.append(f"按参数说明修正了 {n} 处写法（如把 \"5\" 当成 5）")
    return Checked(fixed, "", notes)


# —— 工具名写错（Gemini getToolSuggestion，换成 Python 编辑距离） ——

def distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggest(name: str, names: list[str]) -> str:
    """“ 是不是想用 "a"、"b"？”；一个都不像就空串。"""
    ranked = sorted(names, key=lambda n: (distance(name, n), n))
    close = [n for n in ranked if distance(name, n) <= max(2, int(len(name) * SUGGEST_DISTANCE))][:SUGGEST_MAX]
    if not close:
        return ""
    return " 是不是想用 " + "、".join(f'"{n}"' for n in close) + "？"


def wire(parsed: Parsed) -> str | None:
    """回传给模型的历史里该写的参数：原样合法 → None（不改）；修过 → 修后的 JSON；修不好 → "{}"。"""
    if parsed.args is None:
        return "{}"
    if parsed.repaired:
        return json.dumps(parsed.args, ensure_ascii=False)
    return None
