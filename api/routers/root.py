from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/")
async def root():
    return {
        "message": "IndexTTS 2.0 API Server",
        "version": "2.0.0",
        "endpoints": [
            "/tts - 基础文本转语音（兼容1.0版本）",
            "/tts_v2 - 增强版文本转语音（2.0新功能）",
            "/v1/audio/speech - OpenAI Speech 兼容接口",
            "/v1/audio/transcriptions - OpenAI 语音转写（faster-whisper）",
            "/tts_stream - 流式文本转语音",
            "/v1/audio/voices - 音色列表 / 创建 / 更新 / 删除",
            "/v1/audio/voices/{voice_id}/audio - 试听/下载参考原音频",
        ],
    }
