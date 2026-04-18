"""
IndexTTS API 启动入口（兼容旧路径 `python api_server.py`）。

实现已迁移至 `api/` 包：FastAPI 应用为 `api.main:app`，数据库使用 SQLAlchemy。
"""
import os

if "CUDA_VISIBLE_DEVICES" not in os.environ:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    print("[INFO] CUDA_VISIBLE_DEVICES not set, defaulting to GPU 0")
else:
    print(f"[INFO] Using CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}")

from api.main import app

if __name__ == "__main__":
    import logging
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger("indextts2-api")
    log.info("Starting IndexTTS 2.0 API server")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8002)
