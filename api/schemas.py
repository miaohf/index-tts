from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, model_validator


class TextToSpeechRequest(BaseModel):
    text: str
    client_request_id: Optional[str] = None
    prompt_speech_path: Optional[str] = None
    voice: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_sentence: int = 120
    sentences_bucket_max_size: int = 4
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0


class EnhancedTTSRequest(BaseModel):
    text: str
    client_request_id: Optional[str] = None
    prompt_speech_path: Optional[str] = None
    voice: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_segment: int = 120
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0
    do_sample: bool = True
    emo_audio_prompt: Optional[str] = None
    emo_alpha: float = 1.0
    emo_vector: Optional[List[float]] = None
    use_emo_text: bool = False
    emo_text: Optional[str] = None
    use_random: bool = False
    interval_silence: int = 200
    emo_control_mode: int = 0


class StreamTTSRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    voice: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_segment: int = 120
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0
    do_sample: bool = True
    emo_audio_prompt: Optional[str] = None
    emo_alpha: float = 1.0
    emo_vector: Optional[List[float]] = None
    use_emo_text: bool = False
    emo_text: Optional[str] = None
    use_random: bool = False
    interval_silence: int = 200
    emo_control_mode: int = 0
    max_segment_length: int = 100


class OpenAISpeechRequest(BaseModel):
    model: str
    voice: Optional[str] = None
    input: str
    response_format: Literal["wav", "mp3", "opus"] = "wav"
    prompt_speech_path: Optional[str] = None

    @model_validator(mode="after")
    def voice_or_prompt_path(self) -> "OpenAISpeechRequest":
        has_voice = bool(self.voice and self.voice.strip())
        has_path = bool(self.prompt_speech_path and self.prompt_speech_path.strip())
        if has_voice == has_path:
            raise ValueError("voice 与 prompt_speech_path 必须且只能提供一个")
        return self


class OpenAIVoice(BaseModel):
    """对齐 OpenAI `audio.voice` 资源；扩展字段为 IndexTTS 自有。"""

    id: str
    object: Literal["audio.voice"] = "audio.voice"
    name: str
    created_at: int
    description: str = ""
    language: Optional[str] = None
    gender: Optional[str] = None
    preview_url: Optional[str] = None
    preview_path: Optional[str] = None
    request_count: int = 0
    total_audio_seconds: float = 0.0
    last_used_at: Optional[str] = None
    updated_at: Optional[int] = None


class OpenAIVoiceListResponse(BaseModel):
    object: Literal["list"] = "list"
    data: List[OpenAIVoice]
    has_more: bool = False
    first_id: Optional[str] = None
    last_id: Optional[str] = None


class VoiceInfo(BaseModel):
    """服务层音色 DTO；对外 OpenAI 格式见 ``OpenAIVoice``（其 ``id`` = ``voice_id``）。"""

    voice_id: str
    name: str
    description: str = ""
    language: Optional[str] = None
    gender: Optional[str] = None
    file_name: str
    request_count: int = 0
    total_audio_seconds: float = 0.0
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    audio_url: Optional[str] = None
    audio_path: Optional[str] = None


class VoiceListResponse(BaseModel):
    voices: List[VoiceInfo]
    voice_ids: List[str]
    count: int
    directory: str
    page: int = 1
    page_size: int = 50
    message: Optional[str] = None


class VoiceUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    file_name: Optional[str] = None


class UploadAudioResponse(BaseModel):
    status: str
    message: str
    file_path: str
    voice_name: str
    voice_id: str


class UploadRefAudioResponse(BaseModel):
    status: str
    message: str
    session_id: str
    segment_id: str
    ref_path: str
    file_path: str
    expires_at: str


class VoiceCreateRequest(BaseModel):
    """仅创建音色元数据（不上传音频）。磁盘上可无对应文件，后续再通过 POST /v1/audio/voices 上传音频。"""

    voice_id: str
    name: Optional[str] = None
    description: str = ""
    language: Optional[str] = None
    gender: Optional[str] = None
    file_name: Optional[str] = None
