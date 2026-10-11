"""语音：录音上传 → 文字；文字 → 朗读音频（服务器供应商可用时）。供应商逻辑全在 app/voice.py。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import voice
from ..auth import require_user

router = APIRouter(prefix="/api/voice", dependencies=[Depends(require_user)])
MAX_AUDIO = 10 * 1024 * 1024  # 约 10 分钟


@router.get("/config")
async def config():
    return voice.capabilities()


@router.post("/transcribe")
async def transcribe(file: UploadFile):
    data = await file.read(MAX_AUDIO + 1)
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "录音太长")
    if not data:
        raise HTTPException(400, "没有录到声音")
    try:
        text = await voice.transcribe(file.filename or "voice.webm", data)
    except voice.VoiceError as e:
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        raise HTTPException(503, "语音识别不可用（检查语音配置）") from e
    return {"text": text}


class SpeakIn(BaseModel):
    text: str


@router.post("/speak")
async def speak(body: SpeakIn):
    try:
        audio = await voice.speak(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except voice.VoiceError as e:
        raise HTTPException(503, str(e)) from e
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})
