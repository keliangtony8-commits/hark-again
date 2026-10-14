# 真接口测试（会花一点 Step Plan 额度，约 4 次调用）：没有 STEP_API_KEY 就跳过。
# 直连模式跑一轮完整工具调用（模型调工具 → 工具结果 → 模型作答，思考内容不回传），
# 再跑一次 朗读 → 识别 的往返。不跑数据库：记账用空函数替掉。
# 运行：STEP_API_KEY=sk-... python tests/live_stepfun.py   （国内账号再加 STEP_BASE_URL=https://api.stepfun.com/step_plan/v1）
import os, sys, asyncio, json
key = os.environ.get("STEP_API_KEY")
if not key:
    print("live_stepfun 跳过：没有 STEP_API_KEY"); sys.exit(0)
base = os.environ.get("STEP_BASE_URL", "https://api.stepfun.ai/step_plan/v1")
os.environ.update(DATABASE_URL="sqlite+aiosqlite:///:memory:", LLM_BASE_URL=base, LLM_API_KEY=key,
  STEP_BASE_URL=base, OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32,
  MODEL_MAP=json.dumps({"fast": os.environ.get("LIVE_MODEL", "step-3.7-flash")}), VOICE_PROVIDER="stepfun")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import llm, usage, voice
from app.llm import Reasoning, Turn

recorded = []
async def fake_record(model, kind, p, c, **_):
    recorded.append((model, kind, p, c))
usage.record = fake_record

TOOLS = [{"type": "function", "function": {
    "name": "get_time", "description": "查询某个城市现在的时间",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]


async def turn(messages, tools=None):
    thoughts, text, t = 0, "", None
    async for x in llm.stream_turn(messages, tools, model="fast"):
        if isinstance(x, Reasoning):
            thoughts += 1
        elif isinstance(x, Turn):
            t = x
        else:
            text += x
    return t, thoughts


async def main():
    msgs = [{"role": "system", "content": "需要时间就调用工具，回答一句话。"},
            {"role": "user", "content": "北京现在几点？"}]
    t, thoughts = await turn(msgs, TOOLS)
    assert t.tool_calls and t.tool_calls[0].name == "get_time", t
    assert "北京" in json.loads(t.tool_calls[0].arguments).get("city", ""), t.tool_calls[0].arguments
    print(f"1) 工具调用 OK：{t.tool_calls[0].arguments}（思考片段 {thoughts} 个）")
    msgs.append({"role": "assistant", "content": t.text or None, "tool_calls": [
        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in t.tool_calls]})
    msgs.append({"role": "tool", "tool_call_id": t.tool_calls[0].id, "content": "2026-10-11 16:40"})
    t2, _ = await turn(msgs, TOOLS)
    assert not t2.tool_calls and "16" in t2.text, t2
    print(f"2) 带工具结果作答 OK：{t2.text[:60]}")
    assert len(recorded) == 2 and all(r[1] == "chat" and r[0] == "fast" for r in recorded), recorded
    print(f"3) 记账每次调用一行 OK：{recorded}")

    audio = await voice.speak("明天早上八点提醒我开会。")
    assert audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb", audio[:8]
    text = await voice.transcribe("tts.mp3", audio)
    assert "开会" in text, text
    print(f"4) 朗读 → 识别 OK：{text}")
    print("live_stepfun OK")

asyncio.run(main())
