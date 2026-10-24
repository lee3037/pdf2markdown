import asyncio
import hmac
import hashlib
import json
import re
import shutil
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from filelock import FileLock
from pypdf import PdfReader
from starlette.datastructures import Headers

from .config import load_settings
from .store import Store, atomic_json
from .upstream import NativeClient, UpstreamError


class Guard:
    """Authenticate before multipart parsing; bound even chunked request bodies."""
    def __init__(self, app, token, limit):
        self.app, self.token, self.limit = app, token.encode(), limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        header = Headers(scope=scope).get("authorization", "")
        if not header.startswith("Bearer ") or not hmac.compare_digest(header[7:].encode(), self.token):
            return await JSONResponse({"detail": "Gateway authentication required."}, 401,
                                      headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        if scope["method"] == "POST":
            parts, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                part = message.get("body", b"")
                size += len(part)
                if size > self.limit:
                    return await JSONResponse({"detail": "Request too large."}, 413)(scope, receive, send)
                parts.append(part)
                if not message.get("more_body", False):
                    break
            body, replayed = b"".join(parts), False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def status_body(task):
    # Never expose upstream IDs, internal paths, source names, origins or raw errors.
    task_id = task["task_id"]
    return {"task_id": task_id, "status": task["status"], "error": task.get("error"),
            "status_url": f"/tasks/{task_id}", "result_url": f"/tasks/{task_id}/result"}


async def step(store, client):
    tasks = store.all()
    if any(task.get("uncertain") for task in tasks):
        return
    task = next((t for t in tasks if t["status"] in {"pending", "processing"}), None)
    if task is None:
        return
    task_id = task["task_id"]
    if task["phase"] == "submitting" and not task.get("upstream_id"):
        store.update(task_id, status="failed", phase="failed", uncertain=True, error="submission_uncertain")
        return
    directory = store.directory / task_id
    submitting = False
    try:
        if task["origin"] != client.settings.upstream:
            raise UpstreamError("upstream_configuration_changed", bool(task.get("upstream_id")))
        upstream_id = task.get("upstream_id")
        if upstream_id is None:
            contract = await client.probe()
            if contract["fingerprint"] != task["contract"]:
                raise UpstreamError("upstream_contract_changed")
            options = {k: v for k, v in task["options"].items() if k in contract["fields"]}
            store.update(task_id, phase="submitting")
            submitting = True
            with (directory / "source.pdf").open("rb") as source:
                _, receipt = await client.request("POST", "/tasks", submission=True, data=options,
                    files={"files": ("document.pdf", source, "application/pdf")})
            upstream_id = receipt.get("task_id")
            if not valid_id(upstream_id):
                raise UpstreamError("invalid_submission_receipt", True)
            store.update(task_id, upstream_id=upstream_id, phase="polling", status="processing")
            submitting = False
        _, current = await client.request("GET", "/tasks/" + upstream_id)
        state = current.get("status")
        if current.get("task_id") != upstream_id or state not in {"pending", "processing", "completed", "failed"}:
            # Keep the known ID and slot; a transient bad response must not free capacity.
            store.update(task_id, last_error="invalid_upstream_status")
            return
        if state == "failed":
            raise UpstreamError("upstream_task_failed")
        if state != "completed":
            store.update(task_id, status=state, last_error=None)
            return
        code, payload = await client.request("GET", "/tasks/" + upstream_id + "/result")
        if code == 202:
            return
        atomic_json(directory / "result.json", payload)
        results = payload.get("results")
        result = next(iter(results.values())) if isinstance(results, dict) and len(results) == 1 else None
        if (payload.get("version") != client.settings.expected_version or not isinstance(result, dict)
                or not isinstance(result.get("md_content"), str) or not result["md_content"].strip()
                or len(result["md_content"]) > 1_000_000):
            raise UpstreamError("invalid_upstream_result")
        store.update(task_id, status="completed", phase="completed", last_error=None)
    except UpstreamError as exc:
        if exc.uncertain:
            store.update(task_id, status="failed", phase="failed", error="submission_uncertain", uncertain=True)
        elif task.get("upstream_id") or store.get(task_id).get("upstream_id"):
            if exc.code in {"upstream_connection_failed", "upstream_http_error", "invalid_upstream_json", "upstream_response_too_large"}:
                store.update(task_id, last_error=exc.code)
            else:
                store.update(task_id, status="failed", phase="failed", error=exc.code)
        elif not submitting and exc.code in {"upstream_connection_failed", "upstream_http_error"}:
            store.update(task_id, last_error=exc.code)
        else:
            store.update(task_id, status="failed", phase="failed", error=exc.code)
    except Exception:
        # Do not log PDF contents or raw upstream exceptions. Fail closed if a POST may have happened.
        if store.get(task_id).get("upstream_id") and not submitting:
            store.update(task_id, last_error="gateway_processing_failed")
        else:
            store.update(task_id, status="failed", phase="failed", error="gateway_processing_failed", uncertain=submitting)


async def worker(store, client):
    while True:
        try:
            await step(store, client)
        except Exception:
            # Storage failures must not kill the dispatcher or trigger a second POST.
            pass
        await asyncio.sleep(client.settings.poll_interval)


def create_app(settings=None, transport=None, start_worker=True):
    settings = settings or load_settings()
    store = Store(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app):
        lock = FileLock(str(settings.data_dir / "gateway.lock"), timeout=0)
        lock.acquire()
        client = NativeClient(settings, transport)
        app.state.client = client
        task = None
        try:
            store.recover()
            if start_worker:
                task = asyncio.create_task(worker(store, client))
            app.state.worker = task
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await client.close()
            lock.release()

    app = FastAPI(title="PDF to Markdown Pure Gateway", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(Guard, token=settings.token, limit=settings.max_upload_mb * 1024 * 1024 + 256 * 1024)

    def required(task_id):
        task = store.get(task_id) if valid_id(task_id) else None
        if not task:
            raise HTTPException(404, "Gateway task not found.")
        return task

    async def contract():
        if start_worker and app.state.worker is not None and app.state.worker.done():
            raise HTTPException(503, "Gateway worker stopped.")
        if any(t.get("uncertain") for t in store.all()):
            raise HTTPException(503, "Uncertain submission requires operator review; no automatic resubmission.")
        try:
            return await app.state.client.probe()
        except UpstreamError as exc:
            raise HTTPException(503, "Native MinerU verification failed: " + exc.code) from exc

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi():
        current = await contract()
        schema = app.openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["GatewayBearer"] = {"type": "http", "scheme": "bearer"}
        schema["security"] = [{"GatewayBearer": []}]
        schema["x-pdf2markdown-parser"] = {"upstream_contract": current["fingerprint"],
            "origin_scope": hashlib.sha256(settings.upstream.encode()).hexdigest(),
            "backend": settings.backend or "server-default", "namespace": settings.cache_namespace,
            "version": current["version"]}
        return schema

    @app.get("/health")
    async def health():
        current = await contract()
        return {"status": "healthy", "version": current["version"], "gateway_version": "0.1.0",
                "max_concurrent_tasks": 1, "queued_tasks": sum(t["status"] == "pending" for t in store.all())}

    @app.post("/tasks", status_code=202)
    async def submit(
        files: Annotated[list[UploadFile], File()],
        lang_list: Annotated[list[str], Form()] = ["ch"],
        parse_method: Annotated[str, Form()] = "auto",
        return_md: Annotated[Literal["true"], Form()] = "true",
        return_middle_json: Annotated[Literal["true"], Form()] = "true",
        return_content_list: Annotated[Literal["true"], Form()] = "true",
        response_format_zip: Annotated[Literal["false"], Form()] = "false",
        return_images: Annotated[Literal["false"], Form()] = "false",
        table_enable: Annotated[Literal["true"], Form()] = "true",
        formula_enable: Annotated[Literal["true"], Form()] = "true",
    ):
        try:
            if (len(files) != 1 or parse_method not in {"auto", "txt", "ocr"} or len(lang_list) != 1
                    or not re.fullmatch(r"[a-z_]{2,24}", lang_list[0])):
                raise HTTPException(422, "One PDF and JSON Markdown/structure output are required; unsupported options rejected.")
            current = await contract()
            content = await files[0].read(settings.max_upload_mb * 1024 * 1024 + 1)
            if len(content) > settings.max_upload_mb * 1024 * 1024:
                raise HTTPException(413, "PDF too large.")
            try:
                if not content.lstrip().startswith(b"%PDF-"):
                    raise ValueError()
                reader = PdfReader(BytesIO(content))
                if reader.is_encrypted or not 1 <= len(reader.pages) <= settings.max_pages:
                    raise ValueError()
            except Exception:
                raise HTTPException(422, "Invalid, encrypted or oversized-page-count PDF.")
            task_id = str(uuid4())
            directory = settings.data_dir / task_id
            directory.mkdir()
            try:
                (directory / "source.pdf").write_bytes(content)
                options = {"lang_list": lang_list[0], "parse_method": parse_method, "return_md": "true",
                           "return_middle_json": "true", "return_content_list": "true", "response_format_zip": "false",
                           "return_images": "false", "table_enable": "true", "formula_enable": "true"}
                if settings.backend:
                    options["backend"] = settings.backend
                task = {"task_id": task_id, "status": "pending", "phase": "queued", "upstream_id": None,
                        "origin": settings.upstream, "contract": current["fingerprint"], "options": options, "uncertain": False}
                error = store.add(task, settings.max_pending)
                if error:
                    raise HTTPException(429 if error == "queue_full" else 503, error)
            except BaseException:
                shutil.rmtree(directory)
                raise
            return status_body(task)
        finally:
            for source in files:
                await source.close()

    @app.get("/tasks/{task_id}")
    def status(task_id: str):
        return status_body(required(task_id))

    @app.get("/tasks/{task_id}/result")
    def result(task_id: str):
        task = required(task_id)
        if task["status"] == "failed":
            return JSONResponse(status_body(task), 409)
        if task["status"] != "completed":
            return JSONResponse(status_body(task), 202)
        try:
            return JSONResponse(json.loads((settings.data_dir / task_id / "result.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise HTTPException(500, "Saved gateway result is unavailable; no resubmission performed.")

    return app
