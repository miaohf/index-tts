"""
IndexTTS 2.0 FastAPI 应用入口。

注意：若直接 `uvicorn api.main:app`，需在此文件最前设置 CUDA 环境变量；
或从项目根目录的 `api_server.py` 启动（推荐）。
"""
import os

if "CUDA_VISIBLE_DEVICES" not in os.environ:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import logging

from fastapi import FastAPI

from api.routers import root, speakers, tts, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

_API_DESCRIPTION = """
## IndexTTS 2.0 API 使用说明

### 服务启动
```bash
python api_server.py
# 或: uvicorn api.main:app --host 0.0.0.0 --port 8002
```
默认地址: http://localhost:8002  
交互式文档: http://localhost:8002/docs

### 端点概览
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 服务信息与端点列表 |
| GET | /speakers | 音色列表（SQLAlchemy/SQLite，支持筛选/排序/分页；每条含 `audio_url` 试听） |
| POST | /speakers | 仅创建音色元数据（JSON，无需上传文件） |
| GET | /speakers/{voice_id}/audio | 返回该音色参考音频文件（原文件，供试听/下载） |
| POST | /tts | 基础 TTS（兼容 1.0） |
| POST | /tts_v2 | 增强 TTS（情感控制等） |
| POST | /tts_stream | 流式 TTS |
| POST | /upload_audio | 上传参考音频 |

### 通用说明
- **音色指定**：`prompt_speech_path`（文件名或路径）与 `speaker`（名称）二选一必填；未写路径时从 `assets/speakers/` 下按名称查找。
- **响应**：/tts、/tts_v2 返回 `audio/wav` 二进制；/tts_stream 返回 `application/x-ndjson` 流（每行一个 JSON）。
"""

app = FastAPI(title="IndexTTS 2.0 API", version="2.0.0", description=_API_DESCRIPTION)

app.include_router(root.router)
app.include_router(speakers.router)
app.include_router(tts.router)
app.include_router(upload.router)

# 路由模块在导入时已加载 `api.inference`（初始化模型与音色库）
