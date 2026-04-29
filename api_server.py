#!/usr/bin/env python3
"""
从项目根目录启动 IndexTTS API（B 方案：Redis 队列 + 多 GPU Worker）。

启动后会拉起：
1) 1 个网关进程（对外统一入口，端口默认 8002）
2) N 个 GPU Worker（每卡一进程，消费 Redis 队列）

示例：
  python api_server.py --gpus 1
  python api_server.py --gpus 4 --redis-url redis://127.0.0.1:6379/0
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _terminate_all(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    deadline = time.time() + 30.0
    for p in procs:
        while p.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if p.poll() is None:
            p.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="IndexTTS API（Redis 网关 + 多 GPU Worker）")
    parser.add_argument(
        "--gpus",
        type=int,
        choices=[1, 2, 3, 4],
        default=1,
        metavar="N",
        help="使用几张物理 GPU：在 GPU 0～N-1 上各启动一个 Worker 进程（默认 1）",
    )
    parser.add_argument("--host", default="0.0.0.0", help="网关监听地址")
    parser.add_argument("--port", type=int, default=8002, help="网关端口")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0", help="Redis 连接串")
    parser.add_argument("--queue-name", default="indextts:tts:jobs", help="任务队列名")
    parser.add_argument("--request-queue-name", default="indextts:tts:requests", help="请求队列名（独立于任务队列）")
    parser.add_argument("--job-ttl-seconds", type=int, default=1800, help="任务状态与结果保留秒数")
    parser.add_argument("--max-request-size", type=int, default=200, help="最大活跃请求数（达到上限后拒绝新请求）")
    parser.add_argument(
        "--max-queue-size",
        type=int,
        default=None,
        help="已废弃；保留兼容，等同 --max-request-size",
    )
    args = parser.parse_args()

    max_request_size = args.max_request_size
    if args.max_queue_size is not None:
        max_request_size = args.max_queue_size

    os.chdir(ROOT)

    procs: list[subprocess.Popen] = []

    gateway_env = os.environ.copy()
    gateway_env["INDEX_TTS_REDIS_URL"] = args.redis_url
    gateway_env["INDEX_TTS_QUEUE_NAME"] = args.queue_name
    gateway_env["INDEX_TTS_REQUEST_QUEUE_NAME"] = args.request_queue_name
    gateway_env["INDEX_TTS_JOB_TTL_SECONDS"] = str(args.job_ttl_seconds)
    gateway_env["INDEX_TTS_MAX_REQUEST_SIZE"] = str(max_request_size)
    # 兼容旧代码/旧脚本
    gateway_env["INDEX_TTS_MAX_QUEUE_SIZE"] = str(max_request_size)

    gateway_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.gateway_main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    gateway = subprocess.Popen(gateway_cmd, env=gateway_env, cwd=str(ROOT))
    procs.append(gateway)
    print(
        f"[api_server] 网关已启动: http://{args.host}:{args.port}/docs, redis={args.redis_url}, queue={args.queue_name}",
        flush=True,
    )

    def handle_signal(_sig: int, _frame: object) -> None:
        _terminate_all(procs)
        sys.exit(130)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    n = args.gpus
    for i in range(n):
        env = os.environ.copy()
        full_cmd = [
            sys.executable,
            "api_worker.py",
            "--gpu-id",
            str(i),
            "--redis-url",
            args.redis_url,
            "--queue-name",
            args.queue_name,
            "--job-ttl-seconds",
            str(args.job_ttl_seconds),
        ]
        p = subprocess.Popen(full_cmd, env=env, cwd=str(ROOT))
        procs.append(p)
        print(
            f"[api_server] 已启动 worker {i + 1}/{n}: physical_gpu={i}, queue={args.queue_name}",
            flush=True,
        )

    print(
        f"[api_server] 总计进程: gateway x1 + worker x{n}; 已启用统一入口与服务端队列调度。",
        flush=True,
    )

    exit_code = 0
    try:
        while procs:
            for p in list(procs):
                rc = p.poll()
                if rc is not None:
                    procs.remove(p)
                    if rc != 0:
                        exit_code = rc
            if procs:
                time.sleep(0.25)
    finally:
        _terminate_all(procs)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
