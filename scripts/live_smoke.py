"""Real-service acceptance via local API. A successful probe is required before upload."""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--pdf", type=Path, default=ROOT / "tests/fixtures/sample.pdf")
    parser.add_argument("--expect", default="PDF to Markdown", help="Known source phrase; change for custom PDFs")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    report = {"status": "blocked", "phase": "probe", "conversion_verified": False}
    start = time.monotonic()
    try:
        with httpx.Client(base_url=args.api.rstrip("/") + "/", timeout=20, trust_env=False) as client:
            health = client.get("api/health").raise_for_status().json()
            if health["mode"] != "remote":
                raise ValueError("本机 API 不是 remote 模式，不能进行真实服务验收。")
            probe = client.get("api/mineru/status").raise_for_status().json()
            report["probe"] = probe
            if not probe["available"]:
                raise ValueError(probe["message"])
            report["phase"] = "conversion"
            with args.pdf.open("rb") as source:
                task = client.post("api/tasks", files={"file": (args.pdf.name, source, "application/pdf")}).raise_for_status().json()
            report["task_id"] = task["id"]
            while task["status"] not in {"completed", "failed"}:
                if time.monotonic() - start > args.timeout:
                    raise ValueError("验收等待预算已耗尽，任务保留在工作台，不自动重提。")
                time.sleep(1)
                task = client.get("api/tasks/" + task["id"]).raise_for_status().json()
            if task["status"] != "completed":
                raise ValueError(task.get("error") or "任务失败。")
            reading = client.get(f"api/tasks/{task['id']}/download").raise_for_status().text
            chunked = client.get(f"api/tasks/{task['id']}/download?variant=chunked").raise_for_status().text
            if reading != task["markdown"] or not chunked.strip():
                raise ValueError("导出内容与保存内容不一致，或知识库版为空。")
            canonical = lambda value: re.sub(r"\s+", "", value).casefold()
            if canonical(args.expect) not in canonical(reading):
                raise ValueError("结果未包含已知原文，请人工核对，不能判定转换通过。")
            if task["mode"] != "remote" or "M1 Mock 演示" in reading:
                raise ValueError("发现演示内容，真实转换验收失败。")
            report.update(status="passed", conversion_verified=True, metadata=task["metadata"],
                          characters=len(reading), pages=task["pages"])
    except (httpx.HTTPError, ValueError, OSError, KeyError) as exc:
        report["error"] = str(exc)
    report["elapsed_seconds"] = round(time.monotonic() - start, 3)
    path = ROOT / ".local/live-smoke.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["conversion_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
