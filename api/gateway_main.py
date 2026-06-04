"""
IndexTTS 2.0 网关入口（B 方案：Redis 队列 + GPU Worker）。

该进程不加载推理模型，仅负责：
- 接收请求并入队
- 排队与队列容量控制
- 任务状态查询与结果返回
- 临时参考音 TTL 清理（assets/ephemeral）
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.routers import ref_audio, root_queue, speakers_queue, tts_queue
from api.services.ephemeral_audio import run_cleanup_loop

_API_DESCRIPTION = """
## IndexTTS 2.0 Gateway API（Redis Queue Mode）

### 启动
```bash
python api_server.py --gpus 4 --redis-url redis://127.0.0.1:6379/0
```

### 说明
- 对外 TTS：**POST /v1/audio/speech**（OpenAI 兼容）；
- 视频翻译临时参考音：**POST /ref-audio/upload**（`session_id` 为表单字段，不入库，TTL 自动清理）；
- 网关负责排队与同步等待；推理由 GPU Worker 完成。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(run_cleanup_loop())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="IndexTTS 2.0 Gateway API",
    version="2.0.0",
    description=_API_DESCRIPTION,
    lifespan=lifespan,
)
app.include_router(root_queue.router)
app.include_router(speakers_queue.router)
app.include_router(ref_audio.router)
app.include_router(tts_queue.router)


@app.get("/openai.json", include_in_schema=False)
async def openai_json_compat():
    """OpenClaw 等客户端常误请求 /openai.json，兼容返回 OpenAPI 规范。"""
    return JSONResponse(app.openapi())
