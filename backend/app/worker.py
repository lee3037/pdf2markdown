import logging
import time
from dataclasses import replace

from filelock import FileLock, Timeout

from .config import load_settings
from .mock import MOCK_MARKDOWN
from .store import Store
from .mineru.client import MinerUClient, MinerUError
from .mineru.result import ResultCache, atomic_json, cache_key, normalize

logger = logging.getLogger(__name__)


def process_remote(store: Store, task, client_factory=MinerUClient):
    profile = task["parse_profile"]
    if profile.get("base_url") != store.settings.mineru_base_url:
        raise MinerUError("configuration_changed", "当前解析服务地址与任务创建时不同，请恢复原服务配置后重试。")
    settings = replace(store.settings, mode="remote", mineru_backend=profile.get("backend", ""),
                       parse_method=profile.get("parse_method", "auto"), language=profile.get("language", "ch"))
    client = client_factory(settings)
    cache = ResultCache(settings.data_dir)
    artifact_dir = settings.data_dir / task["id"] / "artifacts"
    started = time.monotonic()
    cached = False
    key = task["cache_key"]
    try:
        payload = None
        contract = None
        upstream_id = task["upstream_id"]
        if not upstream_id:
            store.progress(task["id"], "核实解析服务接口", 15)
            contract = client.discover()
            key = cache_key(task["input_sha256"], client.cache_identity(contract)) if task["input_sha256"] else None
            store.set_cache_key(task["id"], key)
            payload = cache.load(key)
            if payload is not None:
                try:
                    normalize(payload, task["pages"])
                    cached = True
                except MinerUError:
                    payload = None
            if payload is None:
                store.progress(task["id"], "提交 PDF 到 MinerU", 25)
                store.submission(task["id"], True)
                receipt = client.submit(settings.data_dir / task["id"] / "source.pdf", contract)
                if contract.style == "async":
                    upstream_id = client.task_id(receipt.get("task_id"))
                    store.attach_upstream(task["id"], upstream_id)
                    client.validate_status(receipt)
                else:
                    store.submission(task["id"], False)
                    payload = receipt
        while payload is None:
            if time.monotonic() - started > settings.poll_timeout:
                raise MinerUError("poll_timeout", "上游任务仍未完成；已保留任务 ID，重试会继续查询，不重复提交文件。")
            try:
                status = client.status(upstream_id)
            except MinerUError as exc:
                if exc.code == "upstream_not_found":
                    raise MinerUError("upstream_expired", "上游任务已过期或服务已重启；请确认后再重新提交。") from exc
                raise
            state = status["status"]
            if state == "failed":
                if status.get("error") == "submission_uncertain":
                    store.submission(task["id"], True)
                    raise MinerUError("submission_uncertain", "纯解析网关的上游提交结果不确定；请先由网关管理员核实并解除保护，再明确确认是否重新提交。")
                raise MinerUError("upstream_task_failed", "MinerU 任务执行失败，请检查服务端日志后重试。")
            if state == "completed":
                store.progress(task["id"], "下载解析结果", 80)
                payload = client.result(upstream_id)
            else:
                store.progress(task["id"], "MinerU 排队中" if state == "pending" else "MinerU 正在识别正文", 35 if state == "pending" else 55)
            if payload is None:
                time.sleep(settings.poll_interval)
        # Keep raw output before normalization so an incompatible result can be inspected locally.
        atomic_json(artifact_dir / "raw.json", payload)
        parsed = normalize(payload, task["pages"])
        atomic_json(artifact_dir / "document.json", parsed.document)
        (artifact_dir / "original.md").write_text(parsed.markdown, encoding="utf-8")
        # A version mismatch is never cached under the discovered producer identity.
        if not cached and contract is not None and parsed.metadata["producer_version"] == contract.version:
            cache.save(key, payload)
        parsed.metadata.update(cached=cached, elapsed_seconds=round(time.monotonic() - started, 3))
        store.complete(task["id"], parsed.markdown, parsed.metadata)
    except MinerUError as exc:
        if exc.code in {"connection_failed", "authentication_failed", "upstream_not_found"} and not store.get(task["id"])["upstream_id"]:
            store.submission(task["id"], False)
        raise
    finally:
        client.close()


def process_next(store: Store, delay: float = 0.3, client_factory=MinerUClient):
    task = store.claim()
    if not task:
        return False
    try:
        if task["mode"] == "remote":
            process_remote(store, task, client_factory)
        else:
            time.sleep(delay)
            store.progress(task["id"], "准备演示分块", 65)
            time.sleep(delay)
            store.complete(task["id"], MOCK_MARKDOWN)
    except MinerUError as exc:
        store.fail(task["id"], str(exc), exc.code)
    except Exception:
        logger.exception("Task failed: %s", task["id"])
        store.fail(task["id"], "本机处理失败，原文件已保留，请检查本机日志后重试。")
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    store = Store(load_settings())
    try:
        with FileLock(str(store.settings.data_dir / "worker.lock"), timeout=0):
            store.recover()
            logger.info("Worker ready (mode=%s)", store.settings.mode)
            while True:
                if not process_next(store):
                    time.sleep(0.4)
    except Timeout:
        raise SystemExit("该数据目录已有 Worker 运行，请勿重复启动。")
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
