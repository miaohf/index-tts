"""
IndexTTS 2.0 FastAPI 应用入口。

注意：若直接 `uvicorn api.main:app`，需在此文件最前设置 CUDA 环境变量；
多 GPU 负载请从项目根目录运行 `python api_server.py --gpus 1|2|3|4`（每卡一进程、端口递增）。
"""
import os

if "CUDA_VISIBLE_DEVICES" not in os.environ:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.routers import root, transcriptions, tts, voices

_API_DESCRIPTION = """
## IndexTTS 2.0 API 使用说明

### 服务启动
```bash
python api_server.py --gpus 1
# 四卡各一进程（端口 8002～8005）：python api_server.py --gpus 4
# 或单进程: uvicorn api.main:app --host 0.0.0.0 --port 8002
```
默认地址: http://localhost:8002  
交互式文档: http://localhost:8002/docs

### 端点概览
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 服务信息与端点列表 |
| GET | /v1/audio/voices | 音色列表（OpenAI `audio.voice` 格式） |
| POST | /v1/audio/speech | OpenAI 兼容 TTS |
| POST | /v1/audio/transcriptions | OpenAI 兼容语音转写（faster-whisper） |
| GET | /v1/audio/voices/{voice_id}/audio | 试听/下载参考音频 |
| POST | /v1/audio/voices | 上传参考音并创建音色 |
| POST | /tts | 基础 TTS（兼容 1.0） |
| POST | /tts_v2 | 增强 TTS（情感控制等） |
| POST | /tts_stream | 流式 TTS |

### 通用说明
- **音色指定**：`prompt_speech_path`（文件名或路径）与 `voice`（voice_id）二选一必填。
- **响应**：/tts、/tts_v2 返回 `audio/wav` 二进制；/tts_stream 返回 `application/x-ndjson` 流（每行一个 JSON）。
"""

app = FastAPI(title="IndexTTS 2.0 API", version="2.0.0", description=_API_DESCRIPTION)

app.include_router(root.router)
app.include_router(voices.router)
app.include_router(transcriptions.router)
app.include_router(tts.router)


@app.get("/openai.json", include_in_schema=False)
async def openai_json_compat():
    """OpenClaw 等客户端常误请求 /openai.json，兼容返回 OpenAPI 规范。"""
    return JSONResponse(app.openapi())

# 路由模块在导入时已加载 `api.inference`（初始化模型与音色库）
