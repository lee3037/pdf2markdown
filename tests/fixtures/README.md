# 可公开的合成样例

所有文件由项目生成，不含业务资料。

- `sample.pdf`：M1 小型上传样例，内容说明其用于 Mock，不能作为扫描识别验收。
- `live-text.pdf`：两页真实文本 PDF，含中英文标题、段落、列表、三列表格和页码。
- `live-scan.pdf`：同一文档以 180 dpi 栅格化后生成的纯图像 PDF；两页均没有可提取文本。必须经过 OCR 才能取得正文。

两份 live 样例由 `scripts/generate_live_fixtures.py` 生成。重新生成需要 ReportLab、Poppler 以及支持中文的 TrueType 字体：

```sh
uv run --with reportlab python scripts/generate_live_fixtures.py --font /path/to/cjk-font.ttf
```

macOS 默认尝试已安装的 Arial Unicode 字体。字体以子集嵌入文本 PDF，扫描 PDF 不依赖阅读器字体。不要将字体文件提交仓库。更换字体会改变样例字节和排版，应重新渲染检查。

真实转换后需核对至少以下内容，不能只以任务成功认定准确：

| 原文位置 | 已知内容 |
| --- | --- |
| 第 1 页标题 | PDF Conversion Acceptance / 知识库转换验收 |
| 第 1 页正文 | ORCHID-4827；1234.50 CNY |
| 表格表头 | Item / Quantity / Amount (CNY) |
| 表格第 1 行 | Atlas / 3 / 300.00 |
| 表格第 2 行 | Beacon / 7 / 934.50 |
| 第 2 页 | Retrieval Context / 来源与检索上下文；RIVER-9362 |

这些样例仅覆盖清晰的简单排版，不足以证明复杂版面、低质量扫描、跨页续表或长表分块质量。仓库自动测试只检查输入性质；真实服务验收结果单独记录。
