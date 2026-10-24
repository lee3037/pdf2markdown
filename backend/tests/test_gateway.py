"""Offline isolation tests: real FastAPI gateway, simulated native MinerU engine."""
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.pure_gateway.app import create_app, step
from gateway.pure_gateway.config import Settings, validate_upstream
from test_mineru import Gateway, payload, queue

TOKEN = "gateway-test-only-" + "a" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}
PDF = Path(__file__).resolve().parents[2] / "tests/fixtures/live-text.pdf"


@pytest.fixture
def settings(tmp_path):
    return Settings(token=TOKEN, data_dir=tmp_path, poll_interval=0.001)


def web(settings, stub):
    return TestClient(create_app(settings, transport=httpx.MockTransport(stub.handle), start_worker=False))


def upload(client, **options):
    return client.post("/tasks", headers=AUTH, files={"files": ("source.pdf", PDF.read_bytes(), "application/pdf")}, data=options)


def advance(client):
    client.portal.call(step, client.app.state.store, client.app.state.client)


def test_gateway_native_contract_roundtrip_preserves_raw_and_isolates_ids(settings):
    stub = Gateway()
    with web(settings, stub) as client:
        assert client.get("/health", headers=AUTH).json()["version"] == "3.1.1"
        schema = client.get("/openapi.json", headers=AUTH).json()
        assert "/convert/submit" not in schema["paths"] and "/tasks" in schema["paths"]
        accepted = upload(client)
        assert accepted.status_code == 202
        task = accepted.json()
        assert task["task_id"] != "upstream-1" and task["status_url"].startswith("/tasks/")
        assert client.get(task["result_url"], headers=AUTH).status_code == 202
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["status"] == "completed"
        assert client.get(task["result_url"], headers=AUTH).json() == payload()
        assert client.get("/tasks/upstream-1", headers=AUTH).status_code == 404
        raw = settings.data_dir / task["task_id"] / "result.json"
        assert json.loads(raw.read_text()) == payload()
    assert stub.submissions == 1
    assert all(r.url.host == "127.0.0.1" and r.url.port == 58666 for r in stub.requests)
    assert all("authorization" not in r.headers for r in stub.requests)
    post = next(r for r in stub.requests if r.method == "POST")
    assert b'name="return_middle_json"' in post.content and b'name="return_content_list"' in post.content
    assert b'name="backend"' not in post.content


@pytest.mark.parametrize("route,method", [("/health", "GET"), ("/openapi.json", "GET"), ("/tasks", "POST"), ("/tasks/other/result", "GET")])
def test_gateway_auth_is_required_before_parsing_or_upstream_calls(settings, route, method):
    stub = Gateway()
    with web(settings, stub) as client:
        assert client.request(method, route, content=b"not multipart").status_code == 401
        assert client.request(method, route, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert not stub.requests


def test_gateway_queue_limit_and_terminal_state_release_capacity(settings):
    stub = Gateway()
    with web(replace(settings, max_pending=1), stub) as client:
        assert upload(client).status_code == 202
        assert upload(client).status_code == 429
        assert len(list(settings.data_dir.glob("*/source.pdf"))) == 1
        advance(client)
        assert upload(client).status_code == 202


def test_gateway_rejects_invalid_pdf_and_unapproved_output_options(settings):
    stub = Gateway()
    with web(settings, stub) as client:
        assert client.post("/tasks", headers=AUTH, files={"files": ("bad.pdf", b"not a PDF")}).status_code == 422
        assert upload(client, return_md="false").status_code == 422
        assert upload(client, response_format_zip="true").status_code == 422
        assert upload(client, return_images="true").status_code == 422
        assert upload(client, parse_method="other").status_code == 422
    assert stub.submissions == 0


def test_gateway_rejects_oversized_body_before_contacting_upstream(settings):
    stub = Gateway()
    with web(replace(settings, max_upload_mb=1), stub) as client:
        assert client.post("/tasks", headers=AUTH, content=b"x" * (2 * 1024 * 1024)).status_code == 413
    assert not stub.requests


@pytest.mark.parametrize("change", ["version", "schema", "unhealthy"])
def test_gateway_preflight_blocks_unknown_or_unhealthy_native_contract(settings, change):
    stub = Gateway()
    if change == "version":
        stub.version = "3.2.0"
    elif change == "schema":
        stub.schema = {"paths": {"/convert/submit": {"post": {}}}}
    else:
        original = stub.handle
        def unhealthy(request):
            return httpx.Response(503, json={"error": "private"}) if request.url.path == "/health" else original(request)
        stub.handle = unhealthy
    with web(settings, stub) as client:
        assert client.get("/health", headers=AUTH).status_code == 503
        assert upload(client).status_code == 503
    assert stub.submissions == 0


@pytest.mark.parametrize("media,expected", [("application/octet-stream", 200), ("application/json", 503)])
def test_gateway_checks_new_openapi_binary_schema_without_accepting_json_uploads(settings, media, expected):
    stub = Gateway()
    stub.schema["components"]["schemas"]["Body"]["properties"]["files"]["items"] = {"type": "string", "contentMediaType": media}
    with web(settings, stub) as client:
        assert client.get("/health", headers=AUTH).status_code == expected


def test_gateway_uncertain_post_blocks_all_new_submissions_and_is_not_repeated(settings):
    stub = Gateway()
    stub.fail_submit = httpx.ReadTimeout
    with web(settings, stub) as client:
        task = upload(client).json()
        advance(client)
        failed = client.get(task["status_url"], headers=AUTH).json()
        assert failed["status"] == "failed" and failed["error"] == "submission_uncertain"
        assert upload(client).status_code == 503
        advance(client)
    assert stub.submissions == 1
    with web(settings, stub) as client:
        assert client.get("/health", headers=AUTH).status_code == 503
        advance(client)
    assert stub.submissions == 1


def test_gateway_restart_and_transient_query_failure_resume_known_native_id(settings):
    stub = Gateway(status="processing")
    with web(settings, stub) as client:
        task = upload(client).json()
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["status"] == "processing"
    stub.fail_status = httpx.ConnectError
    with web(settings, stub) as client:
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["status"] == "processing"
        stub.fail_status, stub.state = None, "completed"
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["status"] == "completed"
    assert stub.submissions == 1


def test_gateway_crash_during_submission_recovers_as_uncertain(settings):
    stub = Gateway()
    with web(settings, stub) as client:
        task = upload(client).json()
        client.app.state.store.update(task["task_id"], phase="submitting")
    with web(settings, stub) as client:
        assert client.get("/health", headers=AUTH).status_code == 503
        advance(client)
    assert stub.submissions == 0


def test_gateway_preserves_invalid_result_locally_without_mock_success(settings):
    stub = Gateway(result=payload(" "))
    with web(settings, stub) as client:
        task = upload(client).json()
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["status"] == "failed"
        assert client.get(task["result_url"], headers=AUTH).status_code == 409
        assert (settings.data_dir / task["task_id"] / "result.json").exists()


def test_gateway_cannot_forward_client_server_url_or_business_options(settings):
    stub = Gateway()
    with web(settings, stub) as client:
        assert upload(client, server_url="https://other.invalid", callbackUrl="https://other.invalid", backend="vlm-http-client").status_code == 202
        advance(client)
    post = next(r for r in stub.requests if r.method == "POST")
    assert b"other.invalid" not in post.content and b"callbackUrl" not in post.content and b'name="backend"' not in post.content


@pytest.mark.parametrize("url", ["http://127.0.0.1:19091", "http://127.0.0.1:19092", "http://remote.test:58666", "http://user:pass@localhost:58666", "http://localhost:58666/tasks"])
def test_gateway_upstream_cannot_be_old_business_service_or_arbitrary_proxy(url):
    with pytest.raises(ValueError):
        validate_upstream(url)


def test_gateway_and_local_workbench_integrate_with_simulated_native_engine(settings, tmp_path):
    from backend.app.config import Settings as LocalSettings
    from backend.app.mineru.client import MinerUClient
    from backend.app.store import Store as LocalStore
    from backend.app.worker import process_next

    stub = Gateway()
    with web(settings, stub) as client:
        def bridge(request):
            response = client.request(request.method, request.url.path, headers=dict(request.headers), content=request.content)
            if request.method == "POST" and response.status_code == 202:
                advance(client)
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        local = LocalSettings(data_dir=tmp_path / "local", mode="remote", mineru_base_url="http://gateway.test", mineru_api_key=TOKEN)
        store = LocalStore(local)
        task = queue(store)
        assert process_next(store, client_factory=lambda s: MinerUClient(s, httpx.MockTransport(bridge)))
        completed = store.get(task["id"])
        assert completed["status"] == "completed" and completed["mode"] == "remote", completed["error"]
        assert completed["markdown"] == payload()["results"]["document"]["md_content"]
        assert completed["metadata"]["producer_version"] == "3.1.1"
        stub.fail_submit = httpx.ReadTimeout
        uncertain_store = LocalStore(replace(local, cache_namespace="uncertain-test"))
        second = queue(uncertain_store)
        assert process_next(uncertain_store, client_factory=lambda s: MinerUClient(s, httpx.MockTransport(bridge)))
        failed = uncertain_store.get(second["id"])
        assert failed["error_code"] == "submission_uncertain" and failed["submission_started"]
        assert not uncertain_store.retry(second["id"])
        assert stub.submissions == 2


def test_gateway_schema_identity_changes_when_backend_or_namespace_changes(settings):
    stub = Gateway()
    with web(settings, stub) as client:
        first = client.get("/openapi.json", headers=AUTH).json()["x-pdf2markdown-parser"]
    with web(replace(settings, backend="pipeline", cache_namespace="new-model"), stub) as client:
        second = client.get("/openapi.json", headers=AUTH).json()["x-pdf2markdown-parser"]
    assert first != second and second["backend"] == "pipeline" and second["namespace"] == "new-model"


def test_gateway_background_worker_completes_and_does_not_submit_twice(settings):
    stub = Gateway()
    app = create_app(settings, transport=httpx.MockTransport(stub.handle))
    with TestClient(app) as client:
        task = upload(client).json()
        for _ in range(100):
            state = client.get(task["status_url"], headers=AUTH).json()["status"]
            if state == "completed":
                break
            time.sleep(0.005)
        assert state == "completed"
    assert stub.submissions == 1


def test_gateway_invalid_submission_receipt_fails_closed(settings):
    stub = Gateway()
    original = stub.handle
    def invalid(request):
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": "../unknown", "status": "pending"})
        return original(request)
    stub.handle = invalid
    with web(settings, stub) as client:
        task = upload(client).json()
        advance(client)
        assert client.get(task["status_url"], headers=AUTH).json()["error"] == "submission_uncertain"
        assert upload(client).status_code == 503


def test_gateway_single_worker_lock_prevents_duplicate_dispatchers(settings):
    from filelock import Timeout
    with web(settings, Gateway()):
        with pytest.raises(Timeout):
            with web(settings, Gateway()):
                pass
