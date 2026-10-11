"""语音的唯一入口：识别（录音 → 文字）与朗读（文字 → 音频），按 VOICE_PROVIDER 选供应商。

gateway：识别走 llm.transcribe（OpenAI 音频接口 + 网关 stt 别名），朗读交给客户端设备自带语音。
stepfun：识别用 stepaudio-2.5-asr（/audio/asr/sse，base64 + SSE，只收 mp3/wav/ogg/pcm，
         所以 App 的 m4a、网页的 webm 先用 ffmpeg 转成 16k 单声道 wav），朗读用 stepaudio-2.5-tts。
客户端只看 capabilities() 决定朗读走服务器还是设备，不关心供应商。
"""
import asyncio
import base64
import json
import re
import os
import tempfile

import httpx

from . import llm, usage
from .config import settings

TTS_MAX_CHARS = 1000      # 阶跃单次上限；更长的由客户端分段或截断
ASR_DIRECT = {"mp3": "mp3", "wav": "wav", "ogg": "ogg", "opus": "ogg"}  # 扩展名 → 阶跃 format.type


class VoiceError(RuntimeError):
    """给用户看的语音错误（路由转 503）。"""


def capabilities() -> dict:
    """GET /api/voice/config：tts = server（POST /api/voice/speak 可用）| device（用系统语音）。"""
    stepfun = settings.voice_provider == "stepfun" and bool(settings.step_api_key)
    return {"stt": True, "tts": "server" if stepfun else "device"}


def _step_headers() -> dict:
    if not settings.step_api_key:
        raise VoiceError("没有配置 STEP_API_KEY")
    return {"Authorization": f"Bearer {settings.step_api_key}"}


async def transcribe(filename: str, data: bytes) -> str:
    if settings.voice_provider != "stepfun":
        return await llm.transcribe(filename, data)
    fmt, audio = await _for_stepfun(filename, data)
    body = {"audio": {"data": base64.b64encode(audio).decode(), "input": {
        "transcription": {"model": settings.step_asr_model, "language": "zh", "enable_itn": True},
        "format": {"type": fmt}}}}
    text, parts, used = "", [], None
    async with httpx.AsyncClient(timeout=60) as c:
        async with c.stream("POST", f"{settings.step_base_url}/audio/asr/sse", json=body,
                            headers={**_step_headers(), "Accept": "text/event-stream"}) as r:
            if r.status_code != 200:
                raise VoiceError(f"语音识别失败（{r.status_code}）")
            async for line in r.aiter_lines():
                ev = parse_sse(line)
                if ev is None:
                    continue
                if ev.get("type") == "transcript.text.delta":
                    parts.append(ev.get("delta", ""))
                elif ev.get("type") == "transcript.text.done":
                    text, used = ev.get("text", ""), ev.get("usage")
                elif ev.get("type", "").endswith("error"):
                    raise VoiceError(ev.get("message") or "语音识别失败")
    if used:
        await usage.record(settings.step_asr_model, "stt", used.get("input_tokens", 0), used.get("output_tokens", 0))
    return (text or "".join(parts)).strip()


def parse_sse(line: str) -> dict | None:
    """一行 SSE → 事件 dict；空行、注释、[DONE]、坏 JSON 都返回 None。"""
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        ev = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return ev if isinstance(ev, dict) else None


async def _for_stepfun(filename: str, data: bytes) -> tuple[str, bytes]:
    """阶跃直接收的格式原样发；其它（m4a/aac/webm…）转 16k 单声道 wav。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ASR_DIRECT:
        return ASR_DIRECT[ext], data
    return "wav", await to_wav(data, ext)


async def to_wav(data: bytes, ext: str = "") -> bytes:
    """ffmpeg 转码。写临时文件而不是走管道：m4a 的 moov 常在文件尾，管道输入读不到。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, f"in.{ext or 'bin'}")
        with open(src, "wb") as f:
            f.write(data)
        try:
            p = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as e:
            raise VoiceError("服务器没有安装 ffmpeg") from e
        out, err = await asyncio.wait_for(p.communicate(), timeout=60)
    if p.returncode != 0 or not out:
        raise VoiceError("录音格式无法识别")
    return out


def tts_text(text: str) -> str:
    """朗读前的清理：去掉 Markdown 记号；阶跃会把英文括号里的内容当语气指令不读，换成中文括号保住原文。"""

    t = re.sub(r"```.*?```", "（代码略）", text, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = t.replace("(", "（").replace(")", "）")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:TTS_MAX_CHARS]


async def speak(text: str) -> bytes:
    """文字 → mp3。只有 capabilities()['tts'] == 'server' 时可用。"""
    if capabilities()["tts"] != "server":
        raise VoiceError("服务器朗读没有开启（VOICE_PROVIDER=stepfun 且配置 STEP_API_KEY）")
    clean = tts_text(text)
    if not clean:
        raise ValueError("没有可朗读的文字")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{settings.step_base_url}/audio/speech", headers=_step_headers(), json={
            "model": settings.step_tts_model, "voice": settings.step_tts_voice,
            "input": clean, "response_format": "mp3"})
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio"):
        raise VoiceError(f"朗读失败（{r.status_code}）")
    await usage.record(settings.step_tts_model, "tts", len(clean), 0)  # 按字计：输入记字符数
    return r.content
