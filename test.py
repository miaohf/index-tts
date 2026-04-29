#!/usr/bin/env python3
import argparse
import json
import sys
import time
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


def http_get(url: str, timeout: float) -> Tuple[int, Dict[str, str], bytes]:
    req = request.Request(url=url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def parse_json(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


def get_header(headers: Dict[str, str], key: str) -> str:
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="使用文本文件内容调用 IndexTTS 接口并保存音频")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="API 基础地址")
    parser.add_argument("--endpoint", default="tts_v2", choices=["tts", "tts_v2"], help="调用的 TTS 端点")
    parser.add_argument("--text-file", required=True, help="输入文本文件路径")
    parser.add_argument("--speaker", default=None, help="音色名（与 prompt_speech_path 二选一）")
    parser.add_argument("--prompt-speech-path", default=None, help="参考音频路径（与 speaker 二选一）")
    parser.add_argument("--out", default="out.wav", help="输出音频文件路径")
    parser.add_argument("--wait-timeout", type=int, default=20, help="首轮同步等待秒数")
    parser.add_argument("--http-timeout", type=float, default=120.0, help="单次 HTTP 请求超时秒数")
    parser.add_argument("--poll", action="store_true", help="首轮超时后自动轮询并下载音频")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="轮询间隔秒数")
    parser.add_argument("--poll-max-seconds", type=int, default=300, help="最大轮询总时长秒数")
    args = parser.parse_args()

    if not args.speaker and not args.prompt_speech_path:
        print("错误：--speaker 和 --prompt-speech-path 必须至少提供一个", file=sys.stderr)
        return 2

    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        print("错误：文本文件为空", file=sys.stderr)
        return 2

    payload: Dict[str, Any] = {"text": text}
    if args.speaker:
        payload["speaker"] = args.speaker
    if args.prompt_speech_path:
        payload["prompt_speech_path"] = args.prompt_speech_path

    base = args.base_url.rstrip("/")
    tts_url = f"{base}/{args.endpoint}"
    tts_url = f"{tts_url}?{parse.urlencode({'wait_timeout_seconds': args.wait_timeout})}"

    status, headers, body = http_post_json(tts_url, payload, timeout=args.http_timeout)
    content_type = get_header(headers, "Content-Type")

    if status not in (200, 202):
        print(f"请求失败 HTTP {status}", file=sys.stderr)
        if body:
            print(body.decode("utf-8", errors="ignore"), file=sys.stderr)
        return 1

    if content_type.startswith("audio/wav"):
        save_bytes(Path(args.out), body)
        print(f"成功：已保存音频到 {args.out}")
        return 0

    raw_detail = parse_json(body)
    detail = raw_detail.get("detail") if isinstance(raw_detail.get("detail"), dict) else raw_detail
    request_id = detail.get("request_id") if isinstance(detail, dict) else None
    print(f"首轮返回 JSON：{json.dumps(raw_detail, ensure_ascii=False)}")
    if not request_id:
        print("返回中不含 request_id，无法继续拉取音频。", file=sys.stderr)
        return 1

    if not args.poll:
        print(f"你可以手动查询：GET {base}/requests/{request_id}")
        print(f"完成后下载：GET {base}/requests/{request_id}/audio")
        return 0

    deadline = time.time() + args.poll_max_seconds
    status_url = f"{base}/requests/{request_id}"
    audio_url = f"{base}/requests/{request_id}/audio"

    while time.time() < deadline:
        r_status, _, r_body = http_get(status_url, timeout=args.http_timeout)
        if r_status != 200:
            print(f"查询状态失败 HTTP {r_status}", file=sys.stderr)
            print(r_body.decode('utf-8', errors='ignore'), file=sys.stderr)
            return 1

        info = parse_json(r_body)
        job_status = str(info.get("status", "unknown"))
        print(f"request_id={request_id} status={job_status}")

        if job_status == "done":
            a_status, a_headers, a_body = http_get(audio_url, timeout=args.http_timeout)
            a_type = get_header(a_headers, "Content-Type")
            if a_status == 200 and a_type.startswith("audio/wav"):
                save_bytes(Path(args.out), a_body)
                print(f"成功：已保存音频到 {args.out}")
                return 0
            print(f"下载音频失败 HTTP {a_status}", file=sys.stderr)
            print(a_body.decode("utf-8", errors="ignore"), file=sys.stderr)
            return 1

        if job_status == "failed":
            print(f"任务失败：{json.dumps(info, ensure_ascii=False)}", file=sys.stderr)
            return 1

        time.sleep(args.poll_interval)

    print(f"轮询超时（>{args.poll_max_seconds}s），请稍后手动查询 {status_url}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
