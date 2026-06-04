"""项目统一日志格式（对齐 ``timestamp - LEVEL - [file:line] message``）。"""

from __future__ import annotations

import logging
from copy import copy

import click
from uvicorn.logging import AccessFormatter, ColourizedFormatter


class IndexTTSFormatter(ColourizedFormatter):
    """``2026-06-03 20:01:15 - INFO - [main.py:1162] message``"""

    def formatMessage(self, record: logging.LogRecord) -> str:
        recordcopy = copy(record)
        levelname = recordcopy.levelname
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
            if "color_message" in recordcopy.__dict__:
                recordcopy.msg = recordcopy.__dict__["color_message"]
                recordcopy.__dict__["message"] = recordcopy.getMessage()
        recordcopy.__dict__["levelname_fmt"] = levelname
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
        if self.use_colors:
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
        return logging.Formatter.formatMessage(self, recordcopy)
