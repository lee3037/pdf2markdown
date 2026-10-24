import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import Settings

ADAPTER_VERSION = "mineru-3.1.1-v1"


class MinerUError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Contract:
    style: str
    fields: dict
    version: str
    fingerprint: str


def resolve_ref(schema, item):
    """Resolve local OpenAPI refs only; never fetch references from other origins."""
    seen = set()
    while isinstance(item, dict) and "$ref" in item:
        ref = item["$ref"]
        if not ref.startswith("#/") or ref in seen:
            raise MinerUError("invalid_contract", "接口定义包含不支持的引用。")
        seen.add(ref)
        item = schema
        try:
            for part in ref[2:].split("/"):
                item = item[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise MinerUError("invalid_contract", "接口定义中的引用无法解析。")
    if not isinstance(item, dict):
        raise MinerUError("invalid_contract", "接口定义包含非对象结构。")
    return item


class MinerUClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.mineru_base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + settings.mineru_api_key} if settings.mineru_api_key else {},
            timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout),
            trust_env=False, follow_redirects=False, transport=transport,
        )

    def close(self):
        self.http.close()

    def request(self, method, path, *, submission=False, allow=(), **kwargs):
        # Paths are adapter constants, not URLs supplied by the parser.
        try:
            with self.http.stream(method, path.lstrip("/"), **kwargs) as response:
                limit = (64 if path.endswith("/result") or path == "/file_parse" else 4) * 1024 * 1024
                content = bytearray()
                for piece in response.iter_bytes():
                    content.extend(piece)
                    if len(content) > limit:
                        raise MinerUError("result_too_large", "解析服务返回内容超出本工具的大小限制，未截断保存。")
                status = response.status_code
                if status in allow:
                    return status, None
                if status in {401, 403}:
                    raise MinerUError("authentication_failed", "解析服务拒绝访问，请检查本地服务认证配置。")
                if status == 404:
                    raise MinerUError("upstream_not_found", "上游接口或任务不存在；可能未转发该接口，或任务已过期。")
                if status >= 400:
                    raise MinerUError("upstream_http_error", f"解析服务返回 HTTP {status}，请检查服务端日志。")
                if status not in {200, 202}:
                    raise MinerUError("invalid_response", "解析服务返回了意外状态；未跟随重定向或向其他地址发送凭据。")
                try:
                    body = json.loads(content)
                except (ValueError, UnicodeError):
                    raise MinerUError("invalid_response", "解析服务未返回有效 JSON，请检查网关接口。")
                if not isinstance(body, dict):
                    raise MinerUError("invalid_response", "解析服务响应应为 JSON 对象。")
                return status, body
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
            if submission:
                raise MinerUError("submission_uncertain", "提交响应中断，上游可能已接收文件；未自动重复提交。") from exc
            raise MinerUError("connection_failed", "未收到解析服务的有效 HTTP 响应，请检查网络、网关和服务日志。") from exc
        except httpx.HTTPError as exc:
            if submission and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                raise MinerUError("submission_uncertain", "提交响应中断，上游可能已接收文件；未自动重复提交。") from exc
            raise MinerUError("connection_failed", "无法连接解析服务，请检查网络、地址和服务状态。") from exc

    def discover(self):
        _, schema = self.request("GET", "/openapi.json")
        paths = schema.get("paths")
        if not isinstance(paths, dict):
            raise MinerUError("invalid_contract", "接口定义缺少 paths。")
        def has_operation(path, method):
            return isinstance(paths.get(path), dict) and isinstance(paths[path].get(method), dict)
        style = None
        if all(has_operation(path, method) for path, method in [
            ("/tasks", "post"), ("/tasks/{task_id}", "get"), ("/tasks/{task_id}/result", "get")
        ]):
            style = "async"
        elif has_operation("/file_parse", "post"):
            style = "sync"
        if style is None:
            if has_operation("/convert/submit", "post") and has_operation("/convert/task/{task_id}", "get"):
                raise MinerUError("unsupported_contract", "已连接自定义转换网关，但其 OpenAPI 未提供可适配的上传与结果契约；请核实 app.py 的提交认证、上传字段和任务结果格式。")
            raise MinerUError("unsupported_contract", "网关未公开可识别的 MinerU 3.x 接口，请核实 app.py 路由。")
        operation = paths["/tasks" if style == "async" else "/file_parse"]["post"]
        request = resolve_ref(schema, operation.get("requestBody", {}))
        form = request.get("content", {}).get("multipart/form-data", {}).get("schema", {})
        form = resolve_ref(schema, form)
        fields = form.get("properties", {})
        if not isinstance(fields, dict):
            raise MinerUError("invalid_contract", "接口字段定义无效。")
        files = resolve_ref(schema, fields.get("files", {}))
        item = resolve_ref(schema, files.get("items", {}))
        if files.get("type") != "array" or item.get("format") != "binary":
            raise MinerUError("unsupported_contract", "网关的文件上传字段与 MinerU 3.1.1 的 files[] 契约不同。")
        required_fields = {"return_md", "return_middle_json", "return_content_list", "response_format_zip"}
        if not required_fields.issubset(fields):
            raise MinerUError("unsupported_contract", "网关未公开 Markdown 和结构化输出参数，请补齐转发接口。")
        version = ""
        if has_operation("/health", "get"):
            _, health = self.request("GET", "/health")
            version = str(health.get("version", ""))
            if health.get("status") not in {None, "healthy", "ok"}:
                raise MinerUError("upstream_unhealthy", "解析服务健康检查未通过。")
        fingerprint = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        return Contract(style, fields, version, fingerprint)

    def form(self, contract):
        wanted = {"return_md": "true", "return_middle_json": "true", "return_content_list": "true",
                  "response_format_zip": "false", "return_images": "false",
                  "parse_method": self.settings.parse_method, "lang_list": self.settings.language,
                  "table_enable": "true", "formula_enable": "true"}
        if self.settings.mineru_backend:
            wanted["backend"] = self.settings.mineru_backend
        return {key: value for key, value in wanted.items() if key in contract.fields}

    def submit(self, path: Path, contract):
        with path.open("rb") as source:
            _, body = self.request("POST", "/tasks" if contract.style == "async" else "/file_parse",
                                   data=self.form(contract), files={"files": ("document.pdf", source, "application/pdf")},
                                   submission=True)
        if contract.style == "sync":
            return body
        return body

    @staticmethod
    def task_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise MinerUError("invalid_response", "上游未返回有效任务 ID，未自动重提文件。")
        return value

    def validate_status(self, body):
        self.task_id(body.get("task_id"))
        if body.get("status") not in {"pending", "processing", "completed", "failed"}:
            raise MinerUError("invalid_response", "上游任务状态不符合 MinerU 3.1.1 契约。")

    def status(self, task_id):
        _, body = self.request("GET", "/tasks/" + self.task_id(task_id))
        self.validate_status(body)
        if body["task_id"] != task_id:
            raise MinerUError("invalid_response", "上游返回了不匹配的任务 ID。")
        return body

    def result(self, task_id):
        status, body = self.request("GET", "/tasks/" + self.task_id(task_id) + "/result")
        return None if status == 202 else body

    def cache_identity(self, contract):
        # Unknown producer versions cannot safely reuse a prior engine's cache.
        if not contract.version.startswith("3."):
            return None
        return {"adapter": ADAPTER_VERSION, "origin": self.settings.mineru_base_url,
                "version": contract.version, "contract": contract.fingerprint,
                "auth_scope": hashlib.sha256(self.settings.mineru_api_key.encode()).hexdigest(),
                "form": self.form(contract), "namespace": self.settings.cache_namespace}
