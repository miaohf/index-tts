from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/")
async def root():
    return {
        "message": "IndexTTS 2.0 Gateway API (Redis Queue Mode)",
        "version": "2.0.0",
        "mode": "gateway",
        "endpoints": [
            "/tts - 入队并等待（超时返回 request_id）",
            "/tts_v2 - 入队并等待（超时返回 request_id）",
            "/v1/audio/speech - OpenAI Speech 兼容接口",
            "/requests/{request_id} - 查询请求状态",
            "/requests/{request_id}/audio - 获取请求音频",
            "/jobs/{job_id} - 查询任务状态",
            "/jobs/{job_id}/audio - 获取已完成任务音频",
            "/queue/status - 查看队列状态",
        ],
    }
