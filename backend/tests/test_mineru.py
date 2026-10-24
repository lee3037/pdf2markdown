"""Contract simulations based on the verified official 3.1.1 source, not a live gateway."""
import copy
import hashlib
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.mineru.client import MinerUClient, MinerUError
from backend.app.mineru.result import ResultCache, cache_key, normalize
from backend.app.store import Store
from backend.app.worker import process_next
from conftest import pdf_bytes


def schema(style="async"):
    fields = {"files": {"type": "array", "items": {"type": "string", "format": "binary"}}}
    for name in ["return_md", "return_middle_json", "return_content_list", "response_format_zip", "return_images", "table_enable", "formula_enable"]:
        fields[name] = {"type": "boolean"}
    fields.update({"backend": {"type": "string", "default": "hybrid-auto-engine"}, "parse_method": {"type": "string"}, "lang_list": {"type": "array", "items": {"type": "string"}}})
    path = "/tasks" if style == "async" else "/file_parse"
    paths = {path: {"post": {"requestBody": {"content": {"multipart/form-data": {"schema": {"$ref": "#/components/schemas/Body"}}}}}}, "/health": {"get": {}}}
    if style == "async":
        paths.update({"/tasks/{task_id}": {"get": {}}, "/tasks/{task_id}/result": {"get": {}}})
    return {"openapi": "3.1.0", "paths": paths, "components": {"schemas": {"Body": {"type": "object", "properties": fields}}}}


def payload(text="# Native document\n\nInvoice total: 100.50 CNY."):
    return {"version": "3.1.1", "backend": "pipeline", "results": {"document": {
        "md_content": text,
        "middle_json": json.dumps({"pdf_info": [{"page_idx": 0}]}),
        "content_list": json.dumps([{"type": "text", "text": "Invoice total: 100.50 CNY.", "page_idx": 0, "bbox": [0, 0, 100, 100]}]),
    }}}


class Gateway:
    def __init__(self, style="async", status="completed", result=None):
        self.schema = schema(style)
        self.state = status
        self.result = result or payload()
        self.submissions = 0
        self.queries = 0
        self.fail_submit = None
        self.fail_status = None
        self.version = "3.1.1"
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/openapi.json":
            return httpx.Response(200, json=self.schema)
        if path == "/health":
            return httpx.Response(200, json={"status": "healthy", "version": self.version})
        if request.method == "POST":
            self.submissions += 1
            if self.fail_submit:
                raise self.fail_submit("simulated", request=request)
            if path == "/file_parse":
                return httpx.Response(200, json=self.result)
            return httpx.Response(202, json={"task_id": "upstream-1", "status": "pending",
                "status_url": "http://127.0.0.1:58666/tasks/upstream-1", "result_url": "https://untrusted.invalid/steal"})
        if path == "/tasks/upstream-1":
            self.queries += 1
            if self.fail_status:
                raise self.fail_status("simulated", request=request)
            return httpx.Response(200, json={"task_id": "upstream-1", "status": self.state})
        if path == "/tasks/upstream-1/result":
            return httpx.Response(200, json=self.result)
        return httpx.Response(404)

    def factory(self, settings):
        return MinerUClient(settings, transport=httpx.MockTransport(self.handle))


@pytest.fixture
def remote(tmp_path):
    return Settings(data_dir=tmp_path, mode="remote", mineru_base_url="http://mineru.test", mineru_api_key="test-only-secret",
                    poll_interval=0.001, poll_timeout=0.015)


def queue(store):
    body = pdf_bytes()
    with TestClient(create_app(store.settings)) as client:
        task = client.post("/api/tasks", files={"file": ("source.pdf", body, "application/pdf")}).json()
    return store.get(task["id"])


def run(store, gateway):
    assert process_next(store, delay=0, client_factory=gateway.factory)


def test_async_result_artifacts_and_cache_preserve_original(remote):
    store, gateway = Store(remote), Gateway()
    first = queue(store)
    run(store, gateway)
    task = store.get(first["id"])
    assert task["status"] == "completed" and task["mode"] == "remote"
    assert task["upstream_id"] == "upstream-1"
    assert task["metadata"]["producer_version"] == "3.1.1"
    assert "100.50 CNY" in task["markdown"] and "Mock" not in task["markdown"]
    directory = remote.data_dir / first["id"] / "artifacts"
    assert json.loads((directory / "raw.json").read_text()) == gateway.result
    document = json.loads((directory / "document.json").read_text())
    assert document["blocks"][0]["source_pages"] == [1]
    assert (directory / "original.md").read_text() == task["markdown"]
    store.save(task["id"], "# User edit", task["settings"], task["revision"])
    second = queue(store)
    run(store, gateway)
    cached = store.get(second["id"])
    assert cached["metadata"]["cached"] is True and gateway.submissions == 1
    assert cached["markdown"] == payload()["results"]["document"]["md_content"]
    assert all(request.url.host == "mineru.test" for request in gateway.requests)
    post = next(request for request in gateway.requests if request.method == "POST")
    assert b'name="files"' in post.content and b'name="return_content_list"' in post.content
    assert b'name="backend"' not in post.content  # Preserve the deployment default.
    assert "test-only-secret" not in (directory / "document.json").read_text()


def test_sync_fallback_is_discovered_not_assumed(remote):
    store, gateway = Store(remote), Gateway(style="sync")
    task = queue(store)
    run(store, gateway)
    assert store.get(task["id"])["status"] == "completed"
    assert gateway.submissions == 1 and gateway.queries == 0


def test_poll_timeout_retries_the_same_upstream_task(remote):
    store, gateway = Store(remote), Gateway(status="processing")
    task = queue(store)
    run(store, gateway)
    failed = store.get(task["id"])
    assert failed["error_code"] == "poll_timeout" and failed["upstream_id"] == "upstream-1"
    assert store.retry(task["id"])
    gateway.state = "completed"
    run(store, gateway)
    assert store.get(task["id"])["status"] == "completed" and gateway.submissions == 1


def test_worker_restart_resumes_an_existing_task(remote):
    store, gateway = Store(remote), Gateway()
    task = queue(store)
    store.claim()
    store.attach_upstream(task["id"], "upstream-1")
    Store(remote).recover()
    assert store.get(task["id"])["status"] == "queued"
    run(store, gateway)
    assert store.get(task["id"])["status"] == "completed" and gateway.submissions == 0


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError])
def test_uncertain_post_requires_explicit_resubmit(remote, failure):
    store, gateway = Store(remote), Gateway()
    gateway.fail_submit = failure
    task = queue(store)
    run(store, gateway)
    failed = store.get(task["id"])
    assert failed["error_code"] == "submission_uncertain" and failed["submission_started"]
    assert not store.retry(task["id"])
    with TestClient(create_app(remote)) as client:
        assert client.post(f"/api/tasks/{task['id']}/retry").status_code == 409
        assert client.post(f"/api/tasks/{task['id']}/retry", json={"allow_resubmit": True}).status_code == 202
    gateway.fail_submit = None
    run(store, gateway)
    assert store.get(task["id"])["status"] == "completed"


def test_connect_failure_is_not_mock_success(remote):
    store, gateway = Store(remote), Gateway()
    gateway.fail_submit = httpx.ConnectError
    task = queue(store)
    run(store, gateway)
    failed = store.get(task["id"])
    assert failed["status"] == "failed" and failed["markdown"] is None
    assert failed["error_code"] == "connection_failed" and not failed["submission_started"]
    assert store.retry(task["id"])


def test_uncertain_submission_is_not_automatically_recovered(remote):
    store = Store(remote)
    task = queue(store)
    store.claim()
    store.submission(task["id"], True)
    store.recover()
    assert store.get(task["id"])["error_code"] == "submission_uncertain"


def test_remote_json_cannot_leak_profile_or_credentials_to_frontend(remote):
    store, gateway = Store(remote), Gateway()
    task = queue(store)
    run(store, gateway)
    with TestClient(create_app(remote)) as client:
        public = client.get(f"/api/tasks/{task['id']}").json()
        assert public["mode"] == "remote" and "parse_profile" not in public and "cache_key" not in public
        assert "test-only-secret" not in json.dumps(public)
        options = public["settings"] | {"include_source": True, "markdown": public["markdown"], "revision": public["revision"]}
        assert client.put(f"/api/tasks/{task['id']}", json=options).status_code == 200
        exported = client.get(f"/api/tasks/{task['id']}/download?variant=chunked").text
        assert "source.pdf" in exported and "Mock 演示内容" not in exported


def test_custom_gateway_is_rejected_before_sending_a_pdf(remote):
    store, gateway = Store(remote), Gateway()
    gateway.schema = {"paths": {"/convert": {"post": {}}}}
    task = queue(store)
    run(store, gateway)
    assert store.get(task["id"])["error_code"] == "unsupported_contract"
    assert gateway.submissions == 0


def test_observed_convert_gateway_requires_its_actual_contract(remote):
    store, gateway = Store(remote), Gateway()
    gateway.schema = {"paths": {"/convert/submit": {"post": {}}, "/convert/task/{task_id}": {"get": {}}}}
    task = queue(store)
    run(store, gateway)
    failed = store.get(task["id"])
    assert failed["error_code"] == "unsupported_contract"
    assert "已连接自定义转换网关" in failed["error"]
    assert gateway.submissions == 0


def test_m1_database_migrates_without_losing_work(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE tasks (id TEXT PRIMARY KEY,filename TEXT,pages INTEGER,size INTEGER,status TEXT,stage TEXT,
        progress INTEGER,created_at TEXT,updated_at TEXT,markdown TEXT,settings TEXT,revision INTEGER,edited INTEGER,error TEXT,attempts INTEGER)""")
    db.execute("INSERT INTO tasks VALUES ('legacy','old.pdf',1,1,'completed','done',100,'now','now','# Saved','{}',2,1,NULL,1)")
    db.commit()
    db.close()
    task = Store(Settings(data_dir=tmp_path)).get("legacy")
    assert task["markdown"] == "# Saved" and task["revision"] == 2 and task["mode"] == "mock"


@pytest.mark.parametrize("field,value", [("content_list", "broken json"), ("middle_json", []), ("md_content", " ")])
def test_invalid_results_are_preserved_and_never_completed(remote, field, value):
    store, gateway = Store(remote), Gateway()
    gateway.result["results"]["document"][field] = value
    task = queue(store)
    run(store, gateway)
    assert store.get(task["id"])["status"] == "failed"
    assert (remote.data_dir / task["id"] / "artifacts/raw.json").exists()


def test_markdown_only_is_explicitly_flagged():
    raw = payload()
    raw["results"]["document"] = {"md_content": "# Content\n\ntext"}
    parsed = normalize(raw, 1)
    assert not parsed.metadata["structured"] and parsed.metadata["warnings"]


def test_invalid_page_indices_are_not_converted_to_fake_pages():
    raw = payload()
    raw["results"]["document"]["content_list"] = [{"page_idx": value, "type": "text"} for value in [-1, 100, True]]
    assert all(block["source_pages"] == [] for block in normalize(raw, 1).document["blocks"])


def test_corrupt_cache_and_config_changes_cannot_reuse_results(remote):
    client = Gateway().factory(remote)
    contract = client.discover()
    key = cache_key("filehash", client.cache_identity(contract))
    cache = ResultCache(remote.data_dir)
    cache.save(key, payload())
    path = cache.directory / (key + ".json")
    body = json.loads(path.read_text())
    body["payload"]["version"] = "tampered"
    path.write_text(json.dumps(body))
    assert cache.load(key) is None
    changed = copy.deepcopy(client.cache_identity(contract))
    changed["namespace"] = "new-model"
    assert cache_key("filehash", changed) != key
    client.close()


def test_expired_task_requires_confirmation_before_new_submission(remote):
    store, gateway = Store(remote), Gateway()
    task = queue(store)
    store.claim()
    store.attach_upstream(task["id"], "missing-id")
    store.recover()
    run(store, gateway)
    assert store.get(task["id"])["error_code"] == "upstream_expired"
    assert not store.retry(task["id"])
    assert store.retry(task["id"], allow_resubmit=True)
    run(store, gateway)
    assert gateway.submissions == 1 and store.get(task["id"])["status"] == "completed"


@pytest.mark.parametrize("bad", [{"paths": None}, {"paths": {"/tasks": None}}, {"paths": {"/file_parse": {"post": {"requestBody": False}}}}])
def test_malformed_contract_is_a_controlled_failure(remote, bad):
    gateway = Gateway()
    gateway.schema = bad
    client = gateway.factory(remote)
    try:
        with pytest.raises(MinerUError):
            client.discover()
        assert gateway.submissions == 0
    finally:
        client.close()


def test_redirects_and_authentication_errors_do_not_expose_keys(remote):
    seen = []
    def redirect(request):
        seen.append(request.url.host)
        return httpx.Response(307, headers={"Location": "http://other.test/collect"})
    client = MinerUClient(remote, transport=httpx.MockTransport(redirect))
    with pytest.raises(MinerUError, match="未跟随重定向"):
        client.discover()
    assert seen == ["mineru.test"]
    client.close()
    client = MinerUClient(remote, transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "private server message"})))
    with pytest.raises(MinerUError) as caught:
        client.discover()
    assert caught.value.code == "authentication_failed"
    assert "private server message" not in str(caught.value) and remote.mineru_api_key not in str(caught.value)
    client.close()
