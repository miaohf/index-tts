# IndexTTS 2.0 HTTP API

版本：2.0.0 · OpenAPI：`{base}/docs`

```bash
BASE="http://127.0.0.1:8002"   # 下文 {base} 即此地址
```

---

## 1. 两种部署方式

| 方式 | 入口 | 说明 |
|------|------|------|
| **队列模式（推荐生产）** | `python api_server.py` → `api.gateway_main:app` | 1 网关 + N GPU Worker + Redis。对外 TTS 仅 **`POST /v1/audio/speech`**。 |
| **单体模式（开发/调试）** | `uvicorn api.main:app` | 单进程加载模型，同步返回 WAV；另含 `/tts`、`/tts_v2`、`/tts_stream`。 |

### 队列模式启动

```bash
python api_server.py --gpus 4 --host 0.0.0.0 --port 8002 \
  --redis-url redis://127.0.0.1:6379/0 \
  --max-request-size 200
```

| 参数 | 说明 |
|------|------|
| `--gpus` | 1～4，每卡一个 Worker |
| `--redis-url` | Redis 连接串 |
| `--max-request-size` | 最大活跃请求数，满则 **503** |

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `INDEX_TTS_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis |
| `INDEX_TTS_MAX_REQUEST_SIZE` | `200` | 活跃请求上限 |
| `INDEX_TTS_JOB_TTL_SECONDS` | `43200` | 任务结果 Redis 保留时间 |
| `INDEX_TTS_AUTO_SPLIT_THRESHOLD` | `1200` | 超长文本自动分段阈值（0=禁用） |
| `INDEX_TTS_AUTO_SPLIT_SEGMENT_LENGTH` | `1000` | 每段目标字符数 |
| `INDEX_TTS_PUBLIC_BASE_URL` | 无 | 公网前缀，用于 `preview_url` |
| `INDEX_TTS_PROMPT_DIR` | `assets/speakers` | 音色库目录（含 `voices.db`） |
| `INDEX_TTS_MAX_UPLOAD_BYTES` | 50 MiB | 上传大小上限 |

### 单体模式

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8002
```

### 音色库迁移

```bash
uv run alembic upgrade head
# 或离线：uv run python scripts/migrate_voices_db.py --prompt-dir assets/speakers
```

---

## 2. 通用约定

### 音色标识

- **`voice_id`**：业务 ID，与参考音频文件名（无扩展名）一致，如 `Hale.mp3` → `voice_id=Hale`。
- **`id`**：数据库自增主键（内部用）。
- 合成时 JSON 字段名为 **`voice`**（OpenAI 兼容），值为 `voice_id`。

### 参考音频路径 `prompt_speech_path`

与 `voice` **二选一**：

| 形式 | 说明 |
|------|------|
| `file.wav` | 相对音色目录 |
| `voices/file.wav` | 同上（`speakers/` 前缀仍兼容） |
| `ephemeral/{session_id}/{filename}` | 临时参考音，不入库 |

### 队列调用习惯

- 单次 **POST 同步阻塞**：`200` + 音频，或 `504`（增大 `wait_timeout_seconds` 后重试）。
- JSON 正文勿含裸换行，用 `\n` 或 `-d @body.json`。
- 响应为 WAV 时用 `curl -o out.wav`，不要用 `json.tool` 解析。

---

## 3. TTS：`POST /v1/audio/speech`

```
POST {base}/v1/audio/speech?wait_timeout_seconds=180&auto_split=true
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
| `model` | 是 | 兼容字段，任意字符串 |
| `voice` | 是* | 音色 ID；列表见 `GET /v1/audio/voices` |
| `input` | 是 | 合成文本 |
| `response_format` | 否 | `wav`（默认）、`mp3`、`opus` |
| `prompt_speech_path` | 是* | 临时/自定义参考音路径 |

| 查询参数 | 默认 | 说明 |
|----------|------|------|
| `wait_timeout_seconds` | 180 | 1～1800，客户端 HTTP 超时需更大 |
| `auto_split` | true | 超阈值自动多段并行合成 |

```bash
curl -X POST "${BASE}/v1/audio/speech?wait_timeout_seconds=120" \
  -H "Content-Type: application/json" \
  -d '{"model":"indextts","voice":"yeqiantong","input":"你好","response_format":"wav"}' \
  -o output.wav --max-time 130
```

长文本：写入 `body.json` 后 `curl -d @body.json`，`wait_timeout_seconds` 建议 600～1800。

### 单体模式额外接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/tts` | 基础 TTS，请求体用 `voice` 非 `speaker` |
| POST | `/tts_v2` | 增强 TTS（情感参数） |
| POST | `/tts_stream` | NDJSON 流式 |
| POST | `/v1/audio/speech` | 同队列模式 |

`TextToSpeechRequest` 中 `voice` 与 `prompt_speech_path` 二选一；单体 `/tts_v2` 支持 `client_request_id` 幂等。

---

## 4. 音色：`/v1/audio/voices`

OpenAI 风格；网关与单体模式均提供。

### 列表 `GET /v1/audio/voices`

```bash
curl -s "${BASE}/v1/audio/voices?limit=50&language=zh" | jq .
```

| 查询参数 | 说明 |
|----------|------|
| `language` / `gender` | 精确筛选 |
| `search` | 模糊匹配 id/name/description 等 |
| `sort_by` | `voice_id`、`name`、`request_count`、`created_at` 等 |
| `sort_order` | `asc` / `desc` |
| `limit` | 1～200，默认 20 |
| `after` | 分页游标（上一页 `last_id`） |

响应：

```json
{
  "object": "list",
  "data": [
    {
      "id": "yeqiantong",
      "object": "audio.voice",
      "name": "叶倩彤",
      "created_at": 1713524051,
      "description": "...",
      "language": "zh",
      "gender": "female",
      "preview_url": "http://.../v1/audio/voices/yeqiantong/audio",
      "preview_path": "/v1/audio/voices/yeqiantong/audio",
      "request_count": 117,
      "total_audio_seconds": 2496.47,
      "last_used_at": "2026-06-02T15:58:59Z"
    }
  ],
  "has_more": false,
  "first_id": "yeqiantong",
  "last_id": "yeqiantong"
}
```

### 详情 `GET /v1/audio/voices/{voice_id}`

返回单个 `audio.voice` 对象。

### 试听 `GET /v1/audio/voices/{voice_id}/audio`

```bash
curl -s "${BASE}/v1/audio/voices/yeqiantong/audio" -o ref.wav
```

### 创建（含上传）`POST /v1/audio/voices`

`multipart/form-data`，对齐 OpenAI：

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 显示名 |
| `audio_sample` | 是 | 参考音频 `.wav` / `.mp3` |
| `language` | 是 | 如 `zh`、`en` |
| `gender` | 是 | 如 `male`、`female` |
| `description` | 否 | |
| `voice_id` | 否 | 不传则根据 `name` 生成 |

```bash
curl -X POST "${BASE}/v1/audio/voices" \
  -F "audio_sample=@ref.wav" \
  -F "name=我的音色" \
  -F "voice_id=MyVoice" \
  -F "language=zh" \
  -F "gender=female"
```

### 仅元数据 `POST /v1/audio/voices/metadata`

```json
{
  "voice_id": "MyVoice",
  "name": "我的音色",
  "description": "",
  "language": "zh",
  "gender": "female",
  "file_name": "MyVoice.wav"
}
```

### 更新 `PATCH` / `PUT /v1/audio/voices/{voice_id}`

可选字段：`name`、`description`、`language`、`gender`、`file_name`。

### 删除 `DELETE /v1/audio/voices/{voice_id}?remove_file=false`

`remove_file=true` 时同时删除磁盘参考音。

### 数据库表 `voices`（单表）

| 列 | 说明 |
|----|------|
| `id` | 自增主键 |
| `voice_id` | 业务唯一键 |
| `name` / `description` / `language` / `gender` / `file_name` | 元数据 |
| `request_count` / `total_audio_seconds` / `last_used_at` | 使用统计 |
| `created_at` / `updated_at` | ISO 时间 |

---

## 5. 临时参考音：`POST /ref-audio/upload`

视频翻译等场景，**不入库**，TTL 自动清理。

```bash
curl -X POST "${BASE}/ref-audio/upload" \
  -F "source_file=@segment.mp3" \
  -F "session_id=video_id_123"
```

返回 `ref_path`（如 `ephemeral/video_id_123/segment.mp3`），合成时：

```json
{
  "model": "indextts",
  "input": "字幕文本",
  "prompt_speech_path": "ephemeral/video_id_123/segment.mp3",
  "response_format": "wav"
}
```

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `INDEX_TTS_EPHEMERAL_DIR` | `assets/ephemeral` | 临时目录 |
| `INDEX_TTS_EPHEMERAL_TTL_SECONDS` | `86400` | session 生命周期 |
| `INDEX_TTS_EPHEMERAL_CLEANUP_INTERVAL_SECONDS` | `300` | 清理扫描间隔 |

---

## 6. 队列运维（仅网关）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/queue/status` | 队列深度、容量 |
| GET | `/queue/progress` | 任务状态聚合、分段组进度 |
| GET | `/jobs/{job_id}` | 单任务状态 |
| GET | `/jobs/{job_id}/audio` | 单任务 WAV（完成后） |
| GET | `/jobs/group/{group_id}` | 分段组状态 |
| GET | `/jobs/group/{group_id}/audio` | 分段合并 WAV |
| GET | `/requests/{request_id}/audio` | 按 request_id 取音频（备用） |

```bash
curl -s "${BASE}/queue/status" | jq .
curl -s "${BASE}/queue/progress?include_groups=true" | jq .
```

Redis 直查：`LLEN indextts:tts:jobs`、`ZCARD indextts:tts:requests`。

---

## 7. 端点一览

### 队列网关

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/` | 服务信息 |
| POST | `/v1/audio/speech` | **TTS 合成** |
| GET | `/v1/audio/voices` | 音色列表 |
| GET | `/v1/audio/voices/{voice_id}` | 音色详情 |
| POST | `/v1/audio/voices` | 上传参考音并创建 |
| POST | `/v1/audio/voices/metadata` | 仅元数据 |
| PATCH/PUT | `/v1/audio/voices/{voice_id}` | 更新 |
| DELETE | `/v1/audio/voices/{voice_id}` | 删除 |
| GET | `/v1/audio/voices/{voice_id}/audio` | 试听 |
| POST | `/ref-audio/upload` | 临时参考音 |
| GET | `/queue/status` | 队列状态 |

### 单体模式额外

| 方法 | 路径 |
|------|------|
| POST | `/tts`、`/tts_v2`、`/tts_stream` |

---

## 8. 错误码

| HTTP | 含义 |
|------|------|
| 200 | 成功（音频或 JSON） |
| 400 | 参数错误 |
| 404 | 音色/文件/任务不存在 |
| 409 | 任务未完成 |
| 413 | 上传过大 |
| 422 | JSON 非法 |
| 503 | 队列满（网关） |
| 504 | 等待超时（网关） |

---

## 9. 示例与工具

### 测试脚本

```bash
.venv/bin/python test.py --text-file your.txt --voice yeqiantong --wait-timeout 600 -o out.wav
```

### OpenClaw

```yaml
tools:
  tts_speak:
    endpoint: http://127.0.0.1:8002/v1/audio/speech
    method: POST
    query:
      wait_timeout_seconds: 600
    body:
      model: indextts
      voice: "{voice}"
      input: "{text}"
      response_format: wav
```

---

## 10. 代码对应

| 模块 | 路径 |
|------|------|
| 队列网关 | `api/gateway_main.py`、`api/routers/tts_queue.py`、`api/routers/voices.py` |
| GPU Worker | `api_worker.py` |
| 单体 API | `api/main.py`、`api/routers/tts.py` |
| 音色服务 | `api/services/voices.py`、`api/services/voice_read.py`、`api/services/voice_write.py` |
| 请求模型 | `api/schemas.py` |

文档与实现不一致时，以代码与 `{base}/docs` 为准。
