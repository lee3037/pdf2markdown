import logging
import time

from filelock import FileLock, Timeout

from .config import load_settings
from .mock import MOCK_MARKDOWN
from .store import Store

logger = logging.getLogger(__name__)


def process_next(store: Store, delay: float = 0.3):
    task = store.claim()
    if not task:
        return False
    try:
        time.sleep(delay)
        store.progress(task["id"], "准备演示分块", 65)
        time.sleep(delay)
        store.complete(task["id"], MOCK_MARKDOWN)
    except Exception:
        logger.exception("Task failed: %s", task["id"])
        store.fail(task["id"], "演示处理失败，原文件已保留，请重试。")
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    store = Store(load_settings())
    try:
        with FileLock(str(store.settings.data_dir / "worker.lock"), timeout=0):
            store.recover()
            logger.info("M1 Mock worker ready")
            while True:
                if not process_next(store):
                    time.sleep(0.4)
    except Timeout:
        raise SystemExit("该数据目录已有 Worker 运行，请勿重复启动。")
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
