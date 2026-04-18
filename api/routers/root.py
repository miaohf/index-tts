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
            "/tts_stream - 流式文本转语音",
            "/upload_audio - 上传音频文件",
            "/speakers - 获取可用说话人列表；POST /speakers JSON 仅建元数据",
            "/speakers/{voice_id}/audio - 试听/下载参考原音频",
        ],
    }
