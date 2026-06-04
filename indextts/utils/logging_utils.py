"""第三方库日志降噪（避免与 uvicorn DefaultFormatter 冲突）。"""

from __future__ import annotations

import logging

_WETEXT_LOGGER_NAMES = ("wetext-zh_normalizer", "wetext-en_normalizer")


def _reset_wetext_loggers() -> None:
    for name in _WETEXT_LOGGER_NAMES:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.setLevel(logging.WARNING)
        log.propagate = False


def suppress_wetext_normalizer_logs() -> None:
    """
    WeTextProcessing 的 build_fst 会 setLevel(INFO) 并 addHandler(WETEXT 格式)，
    与项目 uvicorn 日志叠加后会出现重复行和错位缩进。
    """
    _reset_wetext_loggers()

    try:
        import tn.processor as processor_module
    except ImportError:
        return

    if getattr(processor_module, "_indextts_logging_patched", False):
        return

    original_build_fst = processor_module.Processor.build_fst

    def build_fst(self, prefix, cache_dir, overwrite_cache):
        log = logging.getLogger(f"wetext-{self.name}")
        log.handlers.clear()
        noop = lambda *args, **kwargs: None
        saved = log.info, log.addHandler, log.setLevel
        log.info = noop
        log.addHandler = noop
        log.setLevel = noop
        try:
            return original_build_fst(self, prefix, cache_dir, overwrite_cache)
        finally:
            log.info, log.addHandler, log.setLevel = saved
            _reset_wetext_loggers()

    processor_module.Processor.build_fst = build_fst
    processor_module._indextts_logging_patched = True
