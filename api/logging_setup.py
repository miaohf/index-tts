"""统一应用日志配置（``timestamp - LEVEL - [file:line] message``）。"""

from __future__ import annotations

import json
import logging
import logging.config
import os
from pathlib import Path

LOG_CONFIG_PATH = Path(__file__).resolve().parent / "uvicorn_log_config.json"


def configure_logging(
    config_path: Path | None = None,
    *,
    level: str | None = None,
) -> None:
    path = config_path or LOG_CONFIG_PATH
    with path.open(encoding="utf-8") as f:
        config = json.load(f)

    log_level = (level or os.environ.get("INDEX_TTS_LOG_LEVEL", "INFO")).upper()
    for name in (
        "root",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "indextts2-api",
        "indextts2-worker",
        "indextts2-launcher",
        "indextts2-infer",
        "indextts2-stt",
        "indextts2-tts",
    ):
        if name in config.get("loggers", {}):
            config["loggers"][name]["level"] = log_level
    if "root" in config:
        config["root"]["level"] = log_level

    logging.config.dictConfig(config)

    from indextts.utils.logging_utils import suppress_wetext_normalizer_logs

    suppress_wetext_normalizer_logs()
