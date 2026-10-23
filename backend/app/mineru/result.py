import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .client import MinerUError


@dataclass
class ParsedDocument:
    markdown: str
    document: dict
    metadata: dict


def json_field(value, kind):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise MinerUError("invalid_result", "上游结构化数据不是有效 JSON，原始响应已保留。")
    if not isinstance(value, kind):
        raise MinerUError("invalid_result", "上游结构化数据类型不符合契约，原始响应已保留。")
    return value


def normalize(payload, page_count):
    results = payload.get("results")
    if not isinstance(results, dict) or len(results) != 1:
        raise MinerUError("invalid_result", "单文件任务应恰好返回一份解析结果，未合并或猜测其他文件内容。")
    result = next(iter(results.values()))
    if not isinstance(result, dict) or not isinstance(result.get("md_content"), str):
        raise MinerUError("invalid_result", "上游结果缺少 Markdown 正文。")
    markdown = result["md_content"]
    if not markdown.strip():
        raise MinerUError("empty_result", "上游返回空正文，请检查原 PDF 或尝试 OCR 模式。")
    if len(markdown) > 1_000_000:
        raise MinerUError("result_too_large", "Markdown 超出当前编辑器限制，原始响应已保留，未截断正文。")
    middle = json_field(result.get("middle_json"), dict)
    content = json_field(result.get("content_list"), (list, dict))
    warnings = []
    if not middle and not content:
        warnings.append("服务仅返回 Markdown；缺少结构化结果，不能可靠定位页码或处理跨页结构。")
    items = content if isinstance(content, list) else []
    blocks = []
    for group in items:
        for block in group if isinstance(group, list) else [group]:
            if not isinstance(block, dict):
                warnings.append("部分结构块格式未知，原始数据已保留。")
                continue
            page_index = block.get("page_idx")
            page = page_index + 1 if isinstance(page_index, int) and not isinstance(page_index, bool) and 0 <= page_index < page_count else None
            blocks.append({"id": f"block-{len(blocks)+1}", "type": block.get("type", "unknown"),
                           "text": block.get("text", ""), "source_pages": [page] if page else [],
                           "bbox": block.get("bbox"), "raw": block})
    if content is not None and not blocks:
        warnings.append("结构化结果已保留，但内容块结构未识别；没有生成虚假的页码映射。")
    if "![" in markdown or "<img" in markdown.lower():
        warnings.append("正文包含图片引用；当前独立 .md 不携带图片文件，预览不加载外部图片。")
    if "<table" in markdown.lower():
        warnings.append("表格保留 MinerU 原始 HTML；Markdown 表格规范化与跨页复核将在 M3 完成。")
    version = str(payload.get("version", "unknown"))
    if not version.startswith("3.1."):
        warnings.append("实际解析服务版本不是已核对的 3.1.x，请复核兼容性。")
    metadata = {"producer": "MinerU", "producer_version": version, "backend": str(payload.get("backend", "unknown")),
                "structured": bool(middle) or bool(content), "block_count": len(blocks),
                "warnings": list(dict.fromkeys(warnings))}
    document = {"schema": "pdf2markdown.document", "schema_version": 1, "page_count": page_count,
                "blocks": blocks, "middle_json": middle, "content_list": content, "metadata": metadata}
    return ParsedDocument(markdown, document, metadata)


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def cache_key(content_hash, identity):
    if identity is None:
        return None
    return hashlib.sha256(json.dumps([content_hash, identity], sort_keys=True).encode()).hexdigest()


class ResultCache:
    def __init__(self, directory):
        self.directory = directory / "cache"

    def load(self, key):
        if not key:
            return None
        try:
            envelope = json.loads((self.directory / (key + ".json")).read_text(encoding="utf-8"))
            body = envelope["payload"]
            if not isinstance(body, dict):
                return None
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            return body if digest == envelope["sha256"] else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, key, payload):
        if key:
            atomic_json(self.directory / (key + ".json"), {"payload": payload,
                        "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})
