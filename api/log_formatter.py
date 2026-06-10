"""项目统一日志格式（对齐 ``timestamp - LEVEL - [file:line] message``）。"""

from __future__ import annotations

import logging
from copy import copy

import click
from uvicorn.logging import AccessFormatter, ColourizedFormatter

# logger 名 → (标签, click 前景色)
_TASK_LOGGER_KIND: dict[str, tuple[str, str]] = {
    "indextts2-stt": ("STT", "cyan"),
    "indextts2-tts": ("TTS", "magenta"),
    "indextts2-infer": ("TTS", "magenta"),
    "indextts2-worker": ("TTS", "magenta"),
}

_TTS_HTTP_PATH_MARKERS = (
    "/v1/audio/speech",
    "/tts_stream",
    "/tts_v2",
    "/tts",
    "/jobs/",
    "/requests/",
)
_STT_HTTP_PATH_MARKERS = ("/v1/audio/transcriptions",)


def _resolve_task_kind(logger_name: str) -> tuple[str, str] | None:
    if logger_name in _TASK_LOGGER_KIND:
        return _TASK_LOGGER_KIND[logger_name]
    for prefix, kind in _TASK_LOGGER_KIND.items():
        if logger_name.startswith(f"{prefix}."):
            return kind
    return None


def _resolve_http_task_kind(path: str) -> tuple[str, str] | None:
    if any(marker in path for marker in _STT_HTTP_PATH_MARKERS):
        return ("STT", "cyan")
    if any(marker in path for marker in _TTS_HTTP_PATH_MARKERS):
        return ("TTS", "magenta")
    return None


def _format_task_tag(kind: tuple[str, str] | None, *, use_colors: bool) -> str:
    if kind is None:
        return ""
    tag, color = kind
    text = f"[{tag}] "
    if use_colors:
        return click.style(text, fg=color, bold=True)
    return text


class IndexTTSFormatter(ColourizedFormatter):
    """``2026-06-03 20:01:15 - INFO - [STT] [main.py:1162] message``"""

    def formatMessage(self, record: logging.LogRecord) -> str:
        recordcopy = copy(record)
        levelname = recordcopy.levelname
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
            if "color_message" in recordcopy.__dict__:
                recordcopy.msg = recordcopy.__dict__["color_message"]
                recordcopy.__dict__["message"] = recordcopy.getMessage()
        recordcopy.__dict__["levelname_fmt"] = levelname
        recordcopy.__dict__["task_fmt"] = _format_task_tag(
            _resolve_task_kind(recordcopy.name),
            use_colors=self.use_colors,
        )
        recordcopy.__dict__["location"] = f"[{recordcopy.filename}:{recordcopy.lineno}]"
        return logging.Formatter.formatMessage(self, recordcopy)


class IndexTTSAccessFormatter(AccessFormatter):
    """HTTP access 日志，LEVEL 不加 uvicorn 的固定宽度 padding。"""

    def formatMessage(self, record: logging.LogRecord) -> str:
        recordcopy = copy(record)
        (
            client_addr,
            method,
            full_path,
            http_version,
            status_code,
        ) = recordcopy.args  # type: ignore[misc]
        status_code = self.get_status_code(int(status_code))  # type: ignore[arg-type]
        request_line = f"{method} {full_path} HTTP/{http_version}"
        http_kind = _resolve_http_task_kind(full_path)
        if self.use_colors:
            if http_kind is not None:
                _, color = http_kind
                request_line = click.style(request_line, fg=color, bold=True)
            else:
                request_line = click.style(request_line, bold=True)
        recordcopy.__dict__.update(
            {
                "client_addr": client_addr,
                "request_line": request_line,
                "status_code": status_code,
            }
        )
        levelname = recordcopy.levelname
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
        recordcopy.__dict__["levelname_fmt"] = levelname
        recordcopy.__dict__["task_fmt"] = _format_task_tag(http_kind, use_colors=self.use_colors)
        return logging.Formatter.formatMessage(self, recordcopy)
