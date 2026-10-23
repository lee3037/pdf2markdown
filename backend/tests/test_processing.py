import pytest

from backend.app.config import Settings
from backend.app.processing import ChunkOptions, export_chunked, make_chunks


def test_heading_paths_and_boundaries():
    text = "# 文档\n\n## 第一节\n\n内容一。\n\n### 子节\n\n内容二。\n\n## 第二节\n\n内容三。"
    chunks = make_chunks(text, ChunkOptions())
    assert [c["section"] for c in chunks] == ["文档 / 第一节", "文档 / 第一节 / 子节", "文档 / 第二节"]
    assert all(c["markdown"].startswith("# 文档") for c in chunks)
    assert "第一节" not in chunks[-1]["markdown"]


def test_lists_and_tables_remain_whole_when_oversized():
    table = "| A | B |\n| --- | --- |\n" + "| 100 | 单位元 |\n" * 30
    text = "# 标题\n\n准备以下材料：\n1. 身份证明\n2. 完整表格\n\n" + table
    chunks = make_chunks(text, ChunkOptions(target_size=100))
    assert len(chunks) == 2
    assert "准备以下材料：\n1. 身份证明\n2. 完整表格" in chunks[0]["markdown"]
    assert chunks[1]["markdown"].split("\n\n", 1)[1].splitlines() == table.splitlines()
    assert chunks[1]["oversized"]


def test_fenced_code_is_not_mistaken_for_a_heading():
    text = "# 文档\n\n```markdown\n# 这是代码\n\n正文\n```\n\n说明。"
    chunks = make_chunks(text, ChunkOptions())
    assert len(chunks) == 1 and chunks[0]["section"] == "文档"
    assert "# 这是代码" in chunks[0]["markdown"]


def test_heading_only_sections_are_preserved():
    text = "# 文档\n\n## 空节\n\n## 正文节\n\n内容\n\n## 尾节"
    chunks = make_chunks(text, ChunkOptions())
    assert len(chunks) == 3
    assert "## 空节" in chunks[0]["markdown"]
    assert chunks[-1]["markdown"].endswith("## 尾节")


def test_empty_and_literal_separator_exports():
    options = ChunkOptions(separator="[.*]\\BOUNDARY")
    assert make_chunks(" \n\n", options) == []
    assert export_chunked("", options) == ""
    exported = export_chunked("# A\n\none\n\n# B\n\ntwo", options)
    assert exported.count(options.separator) == 1
    assert not exported.startswith(options.separator) and not exported.endswith(options.separator)


def test_mock_source_does_not_invent_page_numbers():
    chunk = make_chunks("# 标题\n\n内容", ChunkOptions(include_source=True))[0]
    assert "未建立原 PDF 页码映射" in chunk["markdown"]


def test_remote_mode_requires_an_explicit_service_address(tmp_path):
    with pytest.raises(ValueError, match="MINERU_BASE_URL"):
        Settings(data_dir=tmp_path, mode="remote")


def test_native_html_table_with_blank_lines_remains_one_complete_unit():
    table = '<table>\n<tr><th>费用</th></tr>\n\n<tr><td>' + '100.50 元；' * 25 + '</td></tr>\n</table>'
    chunks = make_chunks('# 表格\n\n' + table + '\n\n表外说明。', ChunkOptions(target_size=100))
    assert len(chunks) == 2
    assert table in chunks[0]['markdown'] and chunks[0]['oversized']
    assert '表外说明' in chunks[1]['markdown']
