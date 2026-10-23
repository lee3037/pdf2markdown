# 合成样例

`sample.pdf` 由 `backend.app.mock.sample_pdf()` 生成，只含公开测试文字，无业务资料。

重新生成：`uv run python scripts/generate_fixture.py`。

M1 Mock 对任何有效 PDF 返回同一份明确标识的示例 Markdown，不代表样例或用户上传文件已被识别。
