#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib import error, parse, request


def http_post_json(url: str, payload: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, str], bytes]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get_header(headers: Dict[str, str], key: str) -> str:
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="调用 OpenAI 兼容 TTS 接口 /v1/audio/speech")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="API 基础地址")
    parser.add_argument("--text-file", required=True, help="输入文本文件路径")
    parser.add_argument("--voice", required=True, help="音色 ID（对应 OpenAI voice）")
    parser.add_argument("--out", default="out.wav", help="输出音频文件路径")
    parser.add_argument(
        "--response-format",
        default="wav",
        choices=["wav", "mp3", "opus"],
        help="OpenAI response_format",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=600,
        help="POST 同步阻塞等待秒数（1～1800）",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=None,
        help="HTTP 客户端超时（默认 wait-timeout + 60）",
    )
    args = parser.parse_args()

    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        print("错误：文本文件为空", file=sys.stderr)
        return 2

    http_timeout = args.http_timeout
    if http_timeout is None:
        http_timeout = float(args.wait_timeout) + 60.0

    base = args.base_url.rstrip("/")
    url = f"{base}/v1/audio/speech?{parse.urlencode({'wait_timeout_seconds': args.wait_timeout})}"
    payload = {
        "model": "indextts",
        "voice": args.voice,
        "input": text,
        "response_format": args.response_format,
    }

    print(f"POST {url}")
    status, headers, body = http_post_json(url, payload, timeout=http_timeout)
    content_type = get_header(headers, "Content-Type")

    if status == 200 and content_type.startswith("audio/"):
        save_bytes(Path(args.out), body)
        print(f"成功：已保存到 {args.out}（{len(body)} bytes, {content_type}）")
        return 0

    print(f"请求失败 HTTP {status}", file=sys.stderr)
    if body:
        print(body.decode("utf-8", errors="ignore"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
