#!/usr/bin/env python3
"""调用 OpenAI 兼容转写接口 POST /v1/audio/transcriptions。"""
import argparse
import json
import mimetypes
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib import error, request


def build_multipart_form(
    fields: Dict[str, str],
    files: Dict[str, Tuple[str, bytes, str]],
) -> Tuple[bytes, str]:
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())

    for name, (filename, data, content_type) in files.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(data)
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def http_post_multipart(url: str, fields: Dict[str, str], files: Dict[str, Tuple[str, bytes, str]], timeout: float) -> Tuple[int, Dict[str, str], bytes]:
    body, content_type = build_multipart_form(fields, files)
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def get_header(headers: Dict[str, str], key: str) -> str:
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="调用 OpenAI 兼容转写接口 /v1/audio/transcriptions")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="API 基础地址")
    parser.add_argument("--audio", required=True, help="待转写音频文件路径")
    parser.add_argument(
        "--model",
        default="whisper-1",
        help="模型名（OpenAI 兼容，实际尺寸见 INDEX_TTS_WHISPER_MODEL）",
    )
    parser.add_argument("--language", default=None, help="ISO-639-1 语言代码，如 zh、en")
    parser.add_argument("--prompt", default=None, help="可选上下文提示")
    parser.add_argument(
        "--response-format",
        default="json",
        choices=["json", "text", "srt", "verbose_json", "vtt"],
        help="响应格式",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="输出文件路径；text/srt/vtt 默认打印到 stdout，json/verbose_json 默认打印 JSON",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=600.0,
        help="HTTP 客户端超时（秒）",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.is_file():
        print(f"错误：音频文件不存在: {audio_path}", file=sys.stderr)
        return 2

    audio_bytes = audio_path.read_bytes()
    if not audio_bytes:
        print("错误：音频文件为空", file=sys.stderr)
        return 2

    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    fields: Dict[str, str] = {
        "model": args.model,
        "response_format": args.response_format,
        "temperature": "0",
    }
    if args.language:
        fields["language"] = args.language
    if args.prompt:
        fields["prompt"] = args.prompt

    base = args.base_url.rstrip("/")
    url = f"{base}/v1/audio/transcriptions"
    files = {"file": (audio_path.name, audio_bytes, content_type)}

    print(f"POST {url}")
    print(f"  audio={audio_path} ({len(audio_bytes)} bytes)")
    print(f"  model={args.model} language={args.language} format={args.response_format}")

    status, headers, body = http_post_multipart(url, fields, files, timeout=args.http_timeout)
    resp_type = get_header(headers, "Content-Type")

    if status != 200:
        print(f"请求失败 HTTP {status}", file=sys.stderr)
        if body:
            print(body.decode("utf-8", errors="ignore"), file=sys.stderr)
        return 1

    text_body = body.decode("utf-8")
    if args.response_format in {"json", "verbose_json"}:
        try:
            parsed: Any = json.loads(text_body)
            output = json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            output = text_body
    else:
        output = text_body

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"成功：已保存到 {out_path}（HTTP {status}, {resp_type}）")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
