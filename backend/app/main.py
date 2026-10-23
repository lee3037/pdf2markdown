import re
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from pypdf import PdfReader

from .config import Settings, load_settings
from .mock import sample_pdf
from .processing import ChunkOptions, export_chunked, make_chunks
from .store import Store


class SaveRequest(ChunkOptions):
    markdown: str = Field(max_length=1_000_000)
    revision: int = Field(ge=1)


def create_app(settings: Settings | None = None):
    settings = settings or load_settings()
    store = Store(settings)
    app = FastAPI(title="PDF to Markdown · M1 Mock", version="0.1.0")
    app.state.store = store

    def required(task_id):
        task = store.get(task_id)
        if not task:
            raise HTTPException(404, "任务不存在。")
        return task

    def detail(task):
        task["mode"] = "mock"
        task["chunks"] = make_chunks(task["markdown"], ChunkOptions(**task["settings"])) if task["markdown"] else []
        return task

    async def accept(filename: str, content: bytes):
        name = filename.replace("\\", "/").split("/")[-1]
        name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:180]
        if not name.lower().endswith(".pdf"):
            raise HTTPException(415, "请选择 PDF 文件。")
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB。")
        if not content.lstrip().startswith(b"%PDF-"):
            raise HTTPException(422, "文件不是有效的 PDF。")
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise HTTPException(422, "暂不支持加密 PDF，请先解密后上传。")
            pages = len(reader.pages)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "PDF 无法读取，文件可能已损坏。")
        if pages < 1 or pages > settings.max_pdf_pages:
            raise HTTPException(422, f"PDF 页数应为 1–{settings.max_pdf_pages} 页。")
        task_id = str(uuid4())
        directory = settings.data_dir / task_id
        directory.mkdir()
        source = directory / "source.pdf"
        try:
            source.write_bytes(content)
            store.create(task_id, name, pages, len(content))
        except Exception:
            source.unlink(missing_ok=True)
            directory.rmdir()
            raise
        return detail(required(task_id))

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "mock", "version": "0.1.0", "max_upload_mb": settings.max_upload_mb,
                "max_pdf_pages": settings.max_pdf_pages,
                "notice": "M1 Mock 演示；未调用 MinerU，不识别上传 PDF 正文。"}

    @app.get("/api/tasks")
    def tasks():
        return [{key: value for key, value in task.items() if key != "markdown"} for task in store.list()]

    @app.post("/api/tasks", status_code=202)
    async def upload(file: UploadFile):
        try:
            data = bytearray()
            while piece := await file.read(1024 * 1024):
                data.extend(piece)
                if len(data) > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB。")
            return await accept(file.filename or "", bytes(data))
        finally:
            await file.close()

    @app.post("/api/tasks/demo", status_code=202)
    async def demo():
        return await accept("示例资料.pdf", sample_pdf())

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        return detail(required(task_id))

    @app.put("/api/tasks/{task_id}")
    def save(task_id: str, request: SaveRequest):
        task = required(task_id)
        if task["status"] != "completed":
            raise HTTPException(409, "任务尚未完成，暂不能编辑。")
        options = ChunkOptions(**request.model_dump())
        try:
            make_chunks(request.markdown, options)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not store.save(task_id, request.markdown, options.model_dump(), request.revision):
            raise HTTPException(409, "内容已被另一个窗口更新，请重新打开任务后再保存。")
        return detail(required(task_id))

    @app.post("/api/tasks/{task_id}/retry", status_code=202)
    def retry(task_id: str):
        required(task_id)
        if not store.retry(task_id):
            raise HTTPException(409, "只有失败或中断的任务可以重试。")
        return detail(required(task_id))

    @app.get("/api/tasks/{task_id}/source")
    def source(task_id: str):
        task = required(task_id)
        return FileResponse(settings.data_dir / task_id / "source.pdf", media_type="application/pdf", filename=task["filename"])

    @app.get("/api/tasks/{task_id}/download")
    def download(task_id: str, variant: str = "reading"):
        task = required(task_id)
        if variant not in {"reading", "chunked"}:
            raise HTTPException(422, "未知导出格式。")
        if task["status"] != "completed":
            raise HTTPException(409, "任务尚未完成。")
        markdown = task["markdown"]
        if variant == "chunked":
            markdown = export_chunked(markdown, ChunkOptions(**task["settings"]))
        name = Path(task["filename"]).stem + (".chunked.md" if variant == "chunked" else ".md")
        return Response(markdown, media_type="text/markdown; charset=utf-8", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
            "Cache-Control": "no-store",
        })

    return app


app = create_app()
