"""语音：录音上传 → 文字。朗读在前端用系统语音合成（免费、离线），后端不参与。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from .. import llm
from ..auth import require_user

router = APIRouter(prefix="/api/voice", dependencies=[Depends(require_user)])
MAX_AUDIO = 10 * 1024 * 1024  # 约 10 分钟


@router.post("/transcribe")
async def transcribe(file: UploadFile):
    data = await file.read(MAX_AUDIO + 1)
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "录音太长")
    if not data:
        raise HTTPException(400, "没有录到声音")
    try:
        text = await llm.transcribe(file.filename or "voice.webm", data)
    except Exception as e:
        raise HTTPException(503, "语音识别不可用（检查 LiteLLM 的 stt 配置）") from e
    return {"text": text}
