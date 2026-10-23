from pathlib import Path

import pytest

from backend.app.main import create_app
from backend.app.processing import ChunkOptions, export_chunked
from backend.app.store import Store
from backend.app.worker import process_next
from conftest import pdf_bytes


def upload(client, name="测试.pdf", content=None):
    return client.post("/api/tasks", files={"file": (name, pdf_bytes() if content is None else content, "application/pdf")})


def completed(client, app):
    task = upload(client).json()
    assert process_next(app.state.store, delay=0)
    return client.get("/api/tasks/" + task["id"]).json()


def test_upload_worker_edit_exports_and_persistence(client, app, settings):
    queued = upload(client).json()
    assert queued["status"] == "queued"
    assert queued["markdown"] is None
    assert queued["pages"] == 1
    assert client.get(f"/api/tasks/{queued['id']}/download").status_code == 409
    assert process_next(app.state.store, delay=0)
    assert not process_next(app.state.store, delay=0)
    task = client.get(f"/api/tasks/{queued['id']}").json()
    assert task["status"] == "completed" and task["progress"] == 100
    assert "不是上传 PDF 的识别结果" in task["markdown"]
    draft = "# 我的文档\n\n## 第一章\n\n单价 100.50 元，编号 A-01。\n\n## 第二章\n\n第二节的完整内容。\n"
    payload = {"markdown": draft, "revision": task["revision"], "separator": "===KNOWLEDGE===",
               "target_size": 100, "include_source": True}
    result = client.put(f"/api/tasks/{task['id']}", json=payload)
    assert result.status_code == 200
    saved = result.json()
    assert saved["edited"] and saved["revision"] == 2
    reading = client.get(f"/api/tasks/{task['id']}/download")
    assert reading.text == draft
    assert "filename*=UTF-8''" in reading.headers["content-disposition"]
    chunked = client.get(f"/api/tasks/{task['id']}/download?variant=chunked")
    assert chunked.text == export_chunked(draft, ChunkOptions(**payload))
    assert chunked.text.count("===KNOWLEDGE===") == len(saved["chunks"]) - 1
    assert "单价 100.50 元，编号 A-01。" in chunked.text
    persisted = Store(settings).get(task["id"])
    assert persisted["markdown"] == draft
    assert persisted["settings"]["separator"] == "===KNOWLEDGE==="
    assert create_app(settings).state.store.get(task["id"])["revision"] == 2


@pytest.mark.parametrize("name,content,status", [
    ("not.txt", b"test", 415),
    ("spoof.pdf", b"not a PDF", 422),
    ("broken.pdf", b"%PDF-1.4\nbroken", 422),
    ("empty.pdf", pdf_bytes(0), 422),
    ("encrypted.pdf", pdf_bytes(password="secret"), 422),
    ("long.pdf", pdf_bytes(4), 422),
    ("large.pdf", b"%PDF-" + b"0" * (1024 * 1024), 413),
])
def test_rejected_uploads_do_not_create_tasks(client, settings, name, content, status):
    assert upload(client, name, content).status_code == status
    assert client.get("/api/tasks").json() == []
    assert not list(settings.data_dir.glob("*/source.pdf"))


def test_filename_paths_are_not_used_as_disk_paths(client, settings):
    task = upload(client, "..\\..\\报告.pdf").json()
    assert task["filename"] == "报告.pdf"
    assert (settings.data_dir / task["id"] / "source.pdf").exists()
    assert client.get(f"/api/tasks/{task['id']}/source").content == pdf_bytes()


def test_optimistic_edit_conflict(client, app):
    task = completed(client, app)
    payload = {"markdown": "# 已编辑\n\n版本二", **task["settings"], "revision": task["revision"]}
    assert client.put(f"/api/tasks/{task['id']}", json=payload).status_code == 200
    assert client.put(f"/api/tasks/{task['id']}", json=payload).status_code == 409


@pytest.mark.parametrize("separator", ["", " ", " new ", "line\nbreak", "tab\tvalue", "a" * 101])
def test_bad_separator_rejected(client, app, separator):
    task = completed(client, app)
    payload = {"markdown": task["markdown"], **task["settings"], "revision": task["revision"], "separator": separator}
    assert client.put(f"/api/tasks/{task['id']}", json=payload).status_code == 422
    assert app.state.store.get(task["id"])["revision"] == 1


def test_separator_conflict_does_not_overwrite(client, app):
    task = completed(client, app)
    payload = {"markdown": "正文===BOUNDARY===正文", **task["settings"], "separator": "===BOUNDARY===", "revision": 1}
    assert client.put(f"/api/tasks/{task['id']}", json=payload).status_code == 422
    assert app.state.store.get(task["id"])["markdown"] == task["markdown"]


def test_interrupted_task_retry_and_single_claim(client, app, settings):
    task = upload(client).json()
    assert app.state.store.claim()["id"] == task["id"]
    assert Store(settings).claim() is None
    app.state.store.recover()
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "failed"
    assert client.post(f"/api/tasks/{task['id']}/retry").status_code == 202
    assert process_next(app.state.store, delay=0)
    assert app.state.store.get(task["id"])["attempts"] == 2
    assert client.post(f"/api/tasks/{task['id']}/retry").status_code == 409


def test_health_demo_and_not_found(client):
    assert client.get("/api/health").json()["mode"] == "mock"
    assert client.post("/api/tasks/demo").status_code == 202
    assert client.get("/api/tasks/not-found").status_code == 404
    assert client.get("/api/tasks/not-found/source").status_code == 404


def test_invalid_export_and_empty_document(client, app):
    task = completed(client, app)
    assert client.get(f"/api/tasks/{task['id']}/download?variant=other").status_code == 422
    response = client.put(f"/api/tasks/{task['id']}", json={"markdown": "", **task["settings"], "revision": 1})
    assert response.status_code == 200 and response.json()["chunks"] == []
    assert client.get(f"/api/tasks/{task['id']}/download?variant=chunked").text == ""


def test_setting_change_does_not_mark_content_edited(client, app):
    task = completed(client, app)
    result = client.put(f"/api/tasks/{task['id']}", json={"markdown": task["markdown"], **task["settings"], "target_size": 100, "revision": 1})
    assert result.status_code == 200
    assert result.json()["edited"] is False
