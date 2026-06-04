from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/")
async def root():
    return {
        "message": "IndexTTS 2.0 Gateway API (Redis Queue Mode)",
        "version": "2.0.0",
        "mode": "gateway",
        "endpoints": [
            "/speakers - 音色列表 / 创建（GET/POST/PUT）/ 删除（DELETE ?voice_id=）",
            "/speakers/{voice_id} - 更新（PATCH/PUT）/ 删除（DELETE）",
            "/speakers/{voice_id}/audio - 试听/下载参考音频",
            "/upload_audio - 上传参考音频并写入音色库",
            "/ref-audio/upload - 上传临时参考音（视频翻译分片，不入库，TTL 自动清理）",
            "/v1/audio/speech - OpenAI Speech 兼容 TTS（voice 或 prompt_speech_path）",
            "/requests/{request_id}/audio?wait_timeout_seconds=... - 按 request_id 同步取音频（备用）",
            "/jobs/{job_id} - 查询任务状态",
            "/jobs/{job_id}/audio - 获取已完成任务音频",
            "/queue/status - 查看队列状态",
        ],
    }
