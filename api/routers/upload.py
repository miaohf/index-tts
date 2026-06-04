import logging

from fastapi import APIRouter, File, Form, UploadFile

from api.schemas import UploadAudioResponse
from api.services.speaker_write import upload_speaker_audio

logger = logging.getLogger("indextts2-api")

router = APIRouter(tags=["upload"])


@router.post("/upload_audio", response_model=UploadAudioResponse)
async def upload_audio(
    source_file: UploadFile = File(...),
    voice_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    language: str = Form(...),
    gender: str = Form(...),
):
    return await upload_speaker_audio(
        source_file=source_file,
        voice_id=voice_id,
        name=name,
        description=description,
        language=language,
        gender=gender,
    )
