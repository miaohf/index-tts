"""
IndexTTS 2.0 网关入口（B 方案：Redis 队列 + GPU Worker）。

该进程不加载推理模型，仅负责：
- 接收请求并入队
- 排队与队列容量控制
- 任务状态查询与结果返回
"""
import logging

from fastapi import FastAPI

from api.routers import root_queue, speakers, tts_queue, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

_API_DESCRIPTION = """
## IndexTTS 2.0 Gateway API（Redis Queue Mode）

### 启动
```bash
python api_server.py --gpus 4 --redis-url redis://127.0.0.1:6379/0
```

### 说明
- 网关负责统一入口、排队、任务查询；
- 推理由独立 GPU Worker 进程完成（每卡一进程）。
"""

app = FastAPI(title="IndexTTS 2.0 Gateway API", version="2.0.0", description=_API_DESCRIPTION)
app.include_router(root_queue.router)
app.include_router(tts_queue.router)
app.include_router(speakers.router)
app.include_router(upload.router)
