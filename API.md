# IndexTTS 2.0 HTTP API

版本：2.0.0  

OpenAPI 交互文档：服务启动后访问 `{base}/docs`（Swagger UI）。

---

## 启动与基址

```bash
# 项目根目录
python api_server.py
# 或
uvicorn api.main:app --host 0.0.0.0 --port 8002
```

默认基址：`http://localhost:8002`（下文记为 `{base}`）。

未设置环境变量 `CUDA_VISIBLE_DEVICES` 时，应用会默认使用 GPU `0`。

### 数据库迁移（Alembic）

音色库使用 SQLite（默认路径：`assets/speakers/voices.db`）。项目已配置 **Alembic**，请在**项目根目录**使用：

```bash
uv run alembic upgrade head    # 新库建表
uv run alembic current         # 查看当前版本
```

- **不要**执行 `python alembic/env.py`；应使用 **`uv run alembic`**（或激活 venv 后的 `alembic`）。
- 若库表已由旧版 `create_all` 建好，请先阅读 `alembic/README` 中的 **`alembic stamp`** 说明，避免重复建表报错。
- 连接串可通过 `ALEMBIC_DATABASE_URL` / `INDEX_TTS_VOICE_DATABASE_URL` 覆盖，详见 `alembic/README`。

### 公网试听链接（`audio_url`）

列表/详情里的 **`audio_url`** 默认按**当前请求的 Host** 生成；本机访问时常为 `http://127.0.0.1:8002/...`，**不适合直接发给他人使用**。

- 部署到公网时，请设置环境变量 **`INDEX_TTS_PUBLIC_BASE_URL`**（例如 `https://tts.example.com`，不要尾随 `/`）。设置后 `audio_url` 会变为 `{INDEX_TTS_PUBLIC_BASE_URL}/speakers/{voice_id}/audio`。
- 响应中的 **`audio_path`** 为相对路径（如 `/speakers/xxx/audio`），前端也可用 **`你的站点公网 origin + audio_path`** 自行拼接。

**说明**：数据库中的 **`file_name`** 表示磁盘上的真实文件名；下载接口路径使用 **`voice_id`**，服务端根据 `voice_id` 查库得到 `file_name` 再读文件，因此 **URL 里不必、也不会**出现 `file_name` 片段。

---

## 通用约定

### 音色与参考音频

- **`id`**：数据库自增主键（`VoiceInfo.id`）。
- **`voice_id`**：业务唯一键，与提示音频文件名（不含扩展名）一致；例如文件 `Bill.mp3` 对应 `voice_id=Bill`。
- **参考音频目录**：默认 `assets/speakers/`（响应里 `directory` 字段会返回实际路径）。
- **音色元数据存储**：该目录下的 `voices.db`（SQLite），由 SQLAlchemy 访问。

### TTS 请求中的音色

以下字段**二选一必填**（若都缺省则返回 400）：

- **`prompt_speech_path`**：参考音频文件名或路径；非绝对路径时按 `assets/speakers/` 下的文件名解析。
- **`speaker`**：音色 ID（即 `voice_id`），在目录或数据库中解析对应文件。

### 内容类型

| 接口 | Content-Type |
|------|----------------|
| `/tts`、`/tts_v2`、`/tts_stream`、`POST /speakers`、`PATCH /speakers/{voice_id}` | `application/json` |
| `/upload_audio` | `multipart/form-data`（**必须**包含 `source_file` 及 `voice_id`、`name`、`description`、`language`、`gender`） |

仅录入元数据、不上传文件时，请使用 **`POST /speakers`**（JSON），不要使用无文件的 `multipart` 调用 `/upload_audio`。

---

## 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息与端点列表 |
| GET | `/speakers` | 音色列表（筛选、排序、分页；含 `audio_url`） |
| POST | `/speakers` | 仅创建音色元数据（JSON） |
| PATCH | `/speakers/{voice_id}` | 更新音色元数据 |
| GET | `/speakers/{voice_id}/audio` | 试听/下载参考原音频 |
| POST | `/tts` | 基础 TTS（兼容 1.0） |
| POST | `/tts_v2` | 增强 TTS（情感等） |
| POST | `/tts_stream` | 流式 TTS（NDJSON） |
| POST | `/upload_audio` | 上传参考音频并写入音色库 |

---

## GET `/`

返回 JSON：`message`、`version`、`endpoints` 说明列表。

---

## GET `/speakers`

返回音色分页列表，并与磁盘上的 `wav`/`mp3` 做一次同步（扫描目录写入/更新库）。

### 查询参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `language` | string | 无 | 按列 `language` **精确**匹配 |
| `gender` | string | 无 | 按列 `gender` **精确**匹配 |
| `category` | string | 无 | 精确匹配分类 |
| `enabled` | boolean | `true` | 是否启用；传 `false` 可查已禁用音色 |
| `search` | string | 无 | 在 `voice_id`、`name`、`description`、`language`、`gender` 中模糊匹配 |
| `label_key` | string | 无 | 存在该标签 key；若同时传 `label_value` 则 key+value 精确匹配 |
| `label_value` | string | 无 | 与 `label_key` 联用 |
| `sort_by` | string | `voice_id` | 允许：`voice_id`、`name`、`language`、`gender`、`created_at`、`updated_at`、`usage_count` |
| `sort_order` | string | `asc` | `asc` 或 `desc` |
| `page` | int | `1` | ≥1 |
| `page_size` | int | `50` | 1～200 |

### 响应体 `SpeakersListResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `voices` | `VoiceInfo[]` | 当前页音色详情 |
| `speakers` | `string[]` | 当前页 `voice_id` 列表 |
| `count` | int | 符合筛选条件的总条数 |
| `directory` | string | 提示音目录路径 |
| `page` | int | 当前页 |
| `page_size` | int | 每页条数 |
| `message` | string? | 提示信息（例如目录不存在时） |

### `VoiceInfo`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 数据库自增主键 |
| `voice_id` | string | 业务唯一键（原「文件名 stem」） |
| `name` | string | 显示名 |
| `description` | string | 描述 |
| `category` | string? | 分类 |
| `language` | string? | 语种 |
| `gender` | string? | 性别等 |
| `file_name` | string | 磁盘上的文件名 |
| `enabled` | boolean | 是否启用 |
| `owner` | string? | 所有者 |
| `version` | string? | 版本 |
| `created_at` | string? | ISO 时间 |
| `updated_at` | string? | ISO 时间 |
| `usage_count` | int | 使用次数统计 |
| `last_used_at` | string? | 最后使用时间 |
| `audio_url` | string? | 完整试听 URL；见上文 `INDEX_TTS_PUBLIC_BASE_URL` |
| `audio_path` | string? | 相对路径 `/speakers/{voice_id}/audio`，便于拼接公网地址 |

响应中**不包含** `labels`；`voice_labels` 表仍保留，创建/更新接口（如 `labels_json`、`PATCH` 的 `labels`）仍可写入，便于日后扩展。

---

## POST `/speakers`

仅写入数据库中的音色元数据，**不要求**磁盘上已存在音频文件。未指定 `file_name` 时，默认 `file_name = "{voice_id}.wav"`，之后可用 **`POST /upload_audio`** 上传音频（表单中指定同一 `voice_id`，磁盘上会保存为 `{voice_id}.wav` 或 `{voice_id}.mp3`）补齐。

**请求体** `VoiceCreateRequest`（JSON）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `voice_id` | string | 是 | 音色 ID |
| `name` | string | 否 | 默认与 `voice_id` 相同 |
| `description` | string | 否 | 默认 `""` |
| `category` | string | 否 | |
| `language` | string | 否 | |
| `gender` | string | 否 | |
| `labels` | object | 否 | 字符串键值对 |
| `owner` | string | 否 | |
| `version` | string | 否 | |
| `enabled` | boolean | 否 | 默认 `true` |
| `file_name` | string | 否 | 库中记录的文件名；默认 `{voice_id}.wav` |

**响应**：`201`，body 为 `VoiceInfo`（含 `audio_url`、`audio_path`）。

---

## PATCH `/speakers/{voice_id}`

部分更新音色元数据。

**路径参数**：`voice_id`

**请求体** `VoiceUpdateRequest`（JSON，字段均可选）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | |
| `description` | string | |
| `category` | string | |
| `language` | string | |
| `gender` | string | |
| `labels` | object | 传入则**整表替换**该音色标签 |
| `enabled` | boolean | |
| `owner` | string | |
| `version` | string | |

**响应**：`VoiceInfo`（含 `audio_url`）。不存在则 `404`。

---

## GET `/speakers/{voice_id}/audio`

根据 **`voice_id`** 查库读取 **`file_name`**，在提示音目录下返回对应磁盘文件（**原文件**）。`Content-Disposition` 为 `inline`，便于浏览器试听。路径中**不包含** `file_name`，避免与 REST 路由冲突；实际文件名以库字段为准。

**路径参数**：`voice_id` 必须为**单一路径段**（不能含 `/`）。

**响应**：音频流；`404` 表示无此音色或文件不在允许路径下。

---

## POST `/upload_audio`

将 `wav` 或 `mp3` 保存到提示音目录，并 upsert 音色记录。磁盘文件名固定为 **`{voice_id}` + 上传文件的扩展名**（例如 `voice_id=my_speaker` 且上传 `x.mp3` 则保存为 `my_speaker.mp3`）。

**Content-Type**：`multipart/form-data`

| 表单字段 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `source_file` | file | 是 | 仅支持 `.wav` / `.mp3` |
| `voice_id` | string | 是 | 音色 ID；不能与路径分隔符等混用 |
| `name` | string | 是 | 显示名称 |
| `description` | string | 是 | 描述（可为空字符串） |
| `language` | string | 是 | 语言 |
| `gender` | string | 是 | 性别 |
| `category` | string | 否 | |
| `owner` | string | 否 | |
| `version` | string | 否 | |
| `enabled` | bool | 否 | 默认 `true` |
| `labels_json` | string | 否 | JSON 对象字符串，解析为标签 |

**成功响应示例**：

```json
{
  "status": "success",
  "message": "音频文件上传成功",
  "file_path": "/path/to/assets/speakers/xxx.mp3",
  "speaker_name": "xxx",
  "voice_id": "xxx"
}
```

缺少必填字段或未上传 `source_file` 时返回 **`422`**（校验）或 **`400`**；仅录入元数据请使用 `POST /speakers`（JSON）。

---

## POST `/tts`

**Content-Type**：`application/json`

**请求体** `TextToSpeechRequest`：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `text` | string | 是 | | 合成文本 |
| `prompt_speech_path` | string | 否* | | 与 `speaker` 二选一 |
| `speaker` | string | 否* | | 与 `prompt_speech_path` 二选一 |
| `temperature` | number | 否 | 0.8 | |
| `top_k` | int | 否 | 30 | |
| `top_p` | number | 否 | 0.8 | |
| `seed` | int | 否 | 421 | |
| `max_text_tokens_per_sentence` | int | 否 | 120 | 内部按句切分相关 |
| `sentences_bucket_max_size` | int | 否 | 4 | |
| `max_mel_tokens` | int | 否 | 1500 | |
| `num_beams` | int | 否 | 3 | |
| `length_penalty` | number | 否 | 0.0 | |
| `repetition_penalty` | number | 否 | 10.0 | |

\* `prompt_speech_path` 与 `speaker` 至少填一个。

**响应**：`audio/wav` 二进制。

---

## POST `/tts_v2`

**Content-Type**：`application/json`

在 `/tts` 基础上增加情感等参数。请求体 `EnhancedTTSRequest`：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `text` | string | 必填 | |
| `prompt_speech_path` / `speaker` | string | 二选一 | 同 `/tts` |
| `temperature` … `repetition_penalty` | | 同左文 | 与生成相关 |
| `do_sample` | boolean | `true` | |
| `emo_audio_prompt` | string? | | 情感参考音频路径（目录内文件名） |
| `emo_alpha` | number | 1.0 | 情感权重 |
| `emo_vector` | float[]? | | 长度 8：`[喜,怒,哀,惧,厌恶,低落,惊喜,平静]` |
| `use_emo_text` | boolean | `false` | |
| `emo_text` | string? | | 情感描述 |
| `use_random` | boolean | `false` | |
| `interval_silence` | int | 200 | 间隔静音(ms) |
| `emo_control_mode` | int | `0` | `0` 与音色参考相同；`1` 情感参考音；`2` 情感向量；`3` 情感文本 |

**响应**：`audio/wav` 二进制。

---

## POST `/tts_stream`

**Content-Type**：`application/json`

按 `max_segment_length`（默认 100）对 `text` 分段，逐段合成并以 **NDJSON**（每行一个 JSON）流式返回。

请求体在 `EnhancedTTSRequest` 基础上增加：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `max_segment_length` | int | 100 | 分段最大字符数 |

**响应**：`Content-Type: application/x-ndjson`

成功时每行 JSON 包含：`text`、`audio`（样本数组）、`sample_rate`、`segment_index`、`total_segments`。

失败时该行可能包含：`error`、`segment_index`、`total_segments`、`text`。

---

## 错误与状态码

| 码 | 含义 |
|----|------|
| 400 | 参数错误（如未提供 `speaker`/`prompt_speech_path`、未上传文件等） |
| 404 | 资源不存在（音色、音频文件等） |
| 422 | JSON 无法解析为约定模型 |
| 500 | 服务器内部错误 |

---

## 与实现的对应关系

- 路由与模型定义见：`api/routers/`、`api/schemas.py`
- 音色持久化：`api/services/voices.py`、`api/database/`
- 推理与全局模型：`api/inference.py`

本文档随版本迭代时，请以代码与 `/docs` 为准。
