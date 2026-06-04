import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

from api.schemas import SpeakersListResponse, VoiceCreateRequest, VoiceInfo, VoiceUpdateRequest
from api.services.speaker_read import download_speaker_audio, list_speakers
from api.services.speaker_write import create_speaker, update_speaker

logger = logging.getLogger("indextts2-api")

router = APIRouter(tags=["speakers"])