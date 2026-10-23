from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


MOCK_MARKDOWN = """# 知识库资料整理指南

> M1 Mock 演示：以下为固定示例，不是上传 PDF 的识别结果。未调用 MinerU，也未提取 PDF 正文。

## 1. 准备一份清晰的资料

一份易于检索的知识资料，应保留完整标题、段落与必要的上下文。准备材料时，请确认文档版本，并检查数字、单位与条款编号。

建议按照以下步骤整理：

1. 上传需要处理的 PDF 文件。
2. 对照原文，检查转换后的 Markdown。
3. 调整分块参数，下载需要的版本。

## 2. 让每个知识块独立可读

分块应尊重章节边界。过长的内容可以在完整段落之间划分，每个知识块保留所属章节路径，避免脱离上下文。

### 2.1 参数参考

| 参数 | 建议值 | 说明 |
| --- | --- | --- |
| 目标大小 | 800 字符 | M1 按完整段落打包，是软目标 |
| 分隔符 | 自定义特殊字符串 | 应避免与正文冲突 |
| 来源说明 | 按需开启 | Mock 模式不提供真实来源页码 |

## 3. 查看与导出

阅读版保持连续 Markdown，适合阅读和后续编辑。知识库版在块之间插入指定分隔符，并在各块重复章节路径。

当前 M1 仅用于验证上传、任务、编辑和导出流程。真实 OCR、跨页表格与复杂结构处理将在后续阶段验证。
"""


def sample_pdf():
    """Public synthetic fixture, generated without business data or fonts."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 22 Tf 50 760 Td (PDF to Markdown - M1 demo) Tj 0 -42 Td /F1 12 Tf (Synthetic PDF. Mock output is a fixed example, not extracted text.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
