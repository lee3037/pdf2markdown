import hashlib
import json

import httpx


class UpstreamError(Exception):
    def __init__(self, code, uncertain=False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


def resolve(schema, value):
    seen = set()
    while isinstance(value, dict) and "$ref" in value:
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
            raise UpstreamError("invalid_contract")
        seen.add(ref)
        value = schema
        try:
            for key in ref[2:].split("/"):
                value = value[key.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise UpstreamError("invalid_contract")
    if not isinstance(value, dict):
        raise UpstreamError("invalid_contract")
    return value


class NativeClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(base_url=settings.upstream + "/", trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(settings.request_timeout, connect=3), transport=transport)

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, *, submission=False, **kwargs):
        try:
            async with self.http.stream(method, path.lstrip("/"), **kwargs) as response:
                limit = (64 if path.endswith("/result") else 4) * 1024 * 1024
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > limit:
                        raise UpstreamError("upstream_response_too_large", submission)
                code = response.status_code
                if code == 404:
                    raise UpstreamError("upstream_expired")
                if code not in {200, 202}:
                    raise UpstreamError("upstream_http_error", submission and (code >= 500 or 300 <= code < 400))
                try:
                    body = json.loads(content)
                except (ValueError, UnicodeError):
                    raise UpstreamError("invalid_upstream_json", submission)
                if not isinstance(body, dict):
                    raise UpstreamError("invalid_upstream_json", submission)
                return code, body
        except httpx.HTTPError as exc:
            uncertain = submission and not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            raise UpstreamError("upstream_connection_failed", uncertain) from exc

    async def probe(self):
        _, schema = await self.request("GET", "/openapi.json")
        paths = schema.get("paths")
        if not isinstance(paths, dict):
            raise UpstreamError("invalid_contract")
        for path, method in [("/tasks", "post"), ("/tasks/{task_id}", "get"), ("/tasks/{task_id}/result", "get"), ("/health", "get")]:
            if not isinstance(paths.get(path), dict) or not isinstance(paths[path].get(method), dict):
                raise UpstreamError("unsupported_native_contract")
        request = resolve(schema, paths["/tasks"]["post"].get("requestBody", {}))
        form = resolve(schema, request.get("content", {}).get("multipart/form-data", {}).get("schema", {}))
        fields = form.get("properties", {})
        if not isinstance(fields, dict):
            raise UpstreamError("invalid_contract")
        files = resolve(schema, fields.get("files", {}))
        item = resolve(schema, files.get("items", {}))
        binary = item.get("type") == "string" and (item.get("format") == "binary" or item.get("contentMediaType") == "application/octet-stream")
        if files.get("type") != "array" or not binary:
            raise UpstreamError("unsupported_upload_contract")
        if not {"return_md", "return_middle_json", "return_content_list", "response_format_zip"}.issubset(fields):
            raise UpstreamError("unsupported_output_contract")
        _, health = await self.request("GET", "/health")
        if health.get("status") != "healthy" or health.get("version") != self.settings.expected_version:
            raise UpstreamError("upstream_health_or_version_mismatch")
        if self.settings.backend and "backend" not in fields:
            raise UpstreamError("unsupported_backend_option")
        return {"version": health["version"], "fields": sorted(fields),
                "fingerprint": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()}
