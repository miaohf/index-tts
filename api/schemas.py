from typing import Dict, List, Optional

from pydantic import BaseModel


class TextToSpeechRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
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
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
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
    speaker: Optional[str] = None
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


class VoiceInfo(BaseModel):
    id: int
    voice_id: str
    name: str
    description: str = ""
    category: Optional[str] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    file_name: str
    enabled: bool = True
    owner: Optional[str] = None
    version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    usage_count: int = 0
    last_used_at: Optional[str] = None
    audio_url: Optional[str] = None
    audio_path: Optional[str] = None


class SpeakersListResponse(BaseModel):
    voices: List[VoiceInfo]
    speakers: List[str]
    count: int
    directory: str
    page: int = 1
    page_size: int = 50
    message: Optional[str] = None


class VoiceUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None
    owner: Optional[str] = None
    version: Optional[str] = None


class VoiceCreateRequest(BaseModel):
    """仅创建音色元数据（不上传音频）。磁盘上可无对应文件，后续再通过 /upload_audio 指定同一 voice_id 上传音频。"""

    voice_id: str
    name: Optional[str] = None
    description: str = ""
    category: Optional[str] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    owner: Optional[str] = None
    version: Optional[str] = None
    enabled: bool = True
    file_name: Optional[str] = None
