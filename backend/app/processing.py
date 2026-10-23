"""M1 heading/paragraph chunking. Advanced table and semantic rules belong to M3."""
import re

from pydantic import BaseModel, Field, field_validator


class ChunkOptions(BaseModel):
    separator: str = Field(default="<<<FASTGPT_CHUNK>>>", min_length=1, max_length=100)
    target_size: int = Field(default=800, ge=100, le=6000)
    include_source: bool = False

    @field_validator("separator")
    @classmethod
    def valid_separator(cls, value):
        if not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("分隔符不能包含换行、控制字符或首尾空白。")
        return value


def make_chunks(markdown: str, options: ChunkOptions, source_note=None):
    if options.separator in markdown:
        raise ValueError("分隔符与正文冲突，请更换分隔符。")
    # Fenced code stays intact even when it contains heading-looking lines.
    units, lines, fence = [], [], None
    html_table_depth = 0
    for line in markdown.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match and not html_table_depth:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
                fence = None
        inside_table = html_table_depth > 0
        if fence is None:
            html_table_depth = max(0, html_table_depth + len(re.findall(r"<table(?:\s|>)", line, re.I)) - len(re.findall(r"</table\s*>", line, re.I)))
            inside_table = inside_table or html_table_depth > 0
        if not line.strip() and fence is None and not inside_table:
            if lines:
                units.append("\n".join(lines))
                lines = []
        elif re.match(r"^#{1,6}\s+", line) and fence is None and not inside_table:
            if lines:
                units.append("\n".join(lines))
            units.append(line)
            lines = []
        else:
            lines.append(line)
    if lines:
        units.append("\n".join(lines))

    headings, body, results = [], [], []
    previous_was_heading = False

    def flush():
        if body:
            prefix = "\n".join("#" * level + " " + title for level, title in headings)
            content = "\n\n".join(body)
            if prefix:
                content = prefix + "\n\n" + content
            if options.include_source:
                content = "> 来源：" + (source_note or "M1 Mock 演示内容；未建立原 PDF 页码映射。") + "\n\n" + content
            results.append({"index": len(results) + 1, "markdown": content,
                            "section": " / ".join(title for _, title in headings) or "正文",
                            "characters": len(content), "oversized": len(content) > options.target_size})
            body.clear()

    for unit in units:
        heading = re.fullmatch(r"(#{1,6})\s+(.+)", unit)
        if heading:
            level = len(heading[1])
            if not body and headings and previous_was_heading:
                # A heading-only sibling is content too; retain it before changing paths.
                if level <= headings[-1][0]:
                    content = "\n".join("#" * depth + " " + title for depth, title in headings)
                    results.append({"index": len(results) + 1, "markdown": content,
                                    "section": " / ".join(title for _, title in headings),
                                    "characters": len(content), "oversized": len(content) > options.target_size})
            flush()
            headings = [(depth, title) for depth, title in headings if depth < level]
            headings.append((level, heading[2]))
            previous_was_heading = True
        else:
            if body and len("\n\n".join(body + [unit])) > options.target_size:
                flush()
            body.append(unit)
            previous_was_heading = False
    flush()
    # Preserve trailing/heading-only sections rather than dropping source content.
    if units and re.fullmatch(r"#{1,6}\s+.+", units[-1]):
        content = "\n".join("#" * level + " " + title for level, title in headings)
        results.append({"index": len(results) + 1, "markdown": content,
                        "section": " / ".join(title for _, title in headings),
                        "characters": len(content), "oversized": len(content) > options.target_size})
    return results


def export_chunked(markdown: str, options: ChunkOptions, source_note=None):
    return ("\n\n" + options.separator + "\n\n").join(chunk["markdown"] for chunk in make_chunks(markdown, options, source_note))
