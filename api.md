# IndexTTS 2.0 API 调用说明

## 1. 服务概述

| 项 | 值 |
|---|---|
| 服务名称 | IndexTTS 2.0 语音合成 |
| 默认地址 | `http://127.0.0.1:8002` |
| TTS 入口 | **`POST /v1/audio/speech`**（OpenAI 兼容，队列网关唯一 TTS 入口） |
| 部署 | `python api_server.py`（Redis 队列 + GPU Worker） |
| 交互文档 | `{base_url}/docs` |
| 鉴权 | 可传 `Authorization: Bearer xxx`（当前不校验） |

队列模式：单次 **POST 同步阻塞**，成功 **200 + 音频**；超时 **504**（增大 `wait_timeout_seconds` 后重试）。

完整字段与错误码见 [`api/API.md`](api/API.md)。

```bash
BASE="http://127.0.0.1:8002"
```

---

## 2. OpenAI Speech 兼容

```
POST {base_url}/v1/audio/speech?wait_timeout_seconds=180
Content-Type: application/json
```

```json
{
  "model": "indextts",
  "voice": "yeqiantong",
  "input": "要合成的文本",
  "response_format": "wav"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `model` | 是 | 任意字符串（兼容字段） |
| `voice` | 是 | 音色 ID（`GET /speakers`） |
| `input` | 是 | 合成文本 |
| `response_format` | 否 | `wav`（默认）、`mp3`、`opus` |

| 查询参数 | 默认 | 说明 |
|----------|------|------|
| `wait_timeout_seconds` | 180 | 同步等待上限（1～1800），HTTP 客户端超时需更大 |
| `auto_split` | true | 超过约 1200 字自动分段并行合成 |

> 队列网关已移除 `/tts`、`/tts_v2`。情感控制等增强参数仅 **单体模式** `uvicorn api.main:app` 仍提供 `/tts_v2`（本地调试）。

### 调用流程

```
POST /v1/audio/speech
  → 200 + audio/*  保存响应体
  → 504          增大 wait_timeout_seconds 后重试
  → 503          队列满，退避
```

### WAV

```bash
curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=120" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "indextts",
    "voice": "yeqiantong",
    "input": "你好，世界！",
    "response_format": "wav"
  }' \
  -o output.wav \
  --max-time 130
```

### MP3 / Opus

```bash
# mp3
curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=120" \
  -H "Content-Type: application/json" \
  -d '{"model":"indextts","voice":"yeqiantong","input":"测试","response_format":"mp3"}' \
  -o output.mp3

# opus（Ogg，需 ffmpeg + libopus）
curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=120" \
  -H "Content-Type: application/json" \
  -d '{"model":"indextts","voice":"yeqiantong","input":"测试","response_format":"opus"}' \
  -o output.ogg
```

长文本示例：

```bash
cat > body.json <<'EOF'
{"model":"indextts","voice":"yeqiantong","input":"很长的正文……","response_format":"wav"}
EOF

curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=900" \
  -H "Content-Type: application/json" \
  -d @body.json \
  -o output.wav \
  --max-time 960
```

Python 示例：

```python
resp = POST("/v1/audio/speech?wait_timeout_seconds=600", json={
    "model": "indextts", "voice": voice_id, "input": text, "response_format": "wav"
}, timeout=660)
```

---

## 3. 健康检查

```bash
curl -s "${BASE}/" | jq .
```

---

## 4. 音色

```bash
curl -s "${BASE}/speakers?page_size=50" | jq .
curl -s "${BASE}/speakers/yeqiantong/audio" -o ref.wav
```

---

## 5. 上传参考音

`multipart/form-data`，必填：`source_file`、`voice_id`、`name`、`description`、`language`、`gender`。单文件默认最大 50 MiB。

```bash
curl -X POST "${BASE}/upload_audio" \
  -F "source_file=@ref.wav" \
  -F "voice_id=MyVoice" \
  -F "name=我的音色" \
  -F "description=描述" \
  -F "language=zh" \
  -F "gender=unknown"
```

成功响应中 `speaker_name` 为写入数据库后的显示名称（`voices.name`），`voice_id` 为业务 ID。

### 视频翻译（临时参考音，不入库）

`session_id` 使用客户端 `video_id`；分片文件名保持原样（如 `8efb100a_0000_SPEAKER_00_vocals.mp3`）：

```bash
VIDEO_ID="8efb100a295c0c690931"

curl -X POST "${BASE}/ref-audio/upload" \
  -F "source_file=@8efb100a295c0c690931_0000_SPEAKER_00_vocals.mp3" \
  -F "session_id=${VIDEO_ID}"

# 返回 ref_path，用于合成（与 voice 二选一）
curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=120" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "indextts",
    "input": "该分片字幕文本",
    "prompt_speech_path": "ephemeral/8efb100a295c0c690931/8efb100a295c0c690931_0000_SPEAKER_00_vocals.mp3",
    "response_format": "wav"
  }' \
  -o segment.wav
```

临时文件保存在 `assets/ephemeral/`，默认 **24h TTL** 后由网关后台任务自动删除（环境变量 `INDEX_TTS_EPHEMERAL_TTL_SECONDS`）。

---

## 6. 队列监控（可选）

```bash
curl -s "${BASE}/queue/status" | jq .
```

---

## 7. 测试脚本

```bash
.venv/bin/python test.py --text-file your.txt --voice yeqiantong --wait-timeout 600 -o out.wav
```

---

## 8. OpenClaw 配置示例

```yaml
tools:
  tts_speak:
    endpoint: http://127.0.0.1:8002/v1/audio/speech
    method: POST
    query:
      wait_timeout_seconds: 600
    body:
      model: indextts
      voice: "{speaker}"
      input: "{text}"
      response_format: wav
```

---

## 9. 端点一览（队列网关）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/v1/audio/speech` | **TTS 合成** |
| GET | `/speakers` | 音色列表 |
| POST | `/upload_audio` | 上传参考音（持久，入库） |
| POST | `/ref-audio/upload` | 上传临时参考音（视频翻译，不入库） |
| GET | `/queue/status` | 队列状态 |
| GET | `/` | 服务信息 |

---

## 10. 错误码

| HTTP | 处理 |
|------|------|
| 200 | 保存音频（看 Content-Type）或 JSON 成功体 |
| 413 | 上传文件过大（默认上限 50 MiB） |
| 422 | 请求参数缺失或 JSON 非法（勿在字符串内裸换行） |
| 503 | 队列满，稍后重试 |
| 504 | 增大 `wait_timeout_seconds` 后重试 |
