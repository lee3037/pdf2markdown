# pdf2markdown

面向知识库资料整理的 PDF 转 Markdown 网页工具。提供 PDF 上传、转换、原文对照、Markdown 编辑、分块预览和下载。下载结果可由用户自行导入 FastGPT 等知识库。

当前状态：M1 基础闭环已验收。M2 已实现原生协议适配和独立 19092 纯解析网关，含独立环境、认证、持久化队列、恢复与 Windows 部署脚本；目标 Windows 的 58666 实例尚未核实，新网关待部署，真实 PDF 转换仍未完成验收。工作分支为 `feat/m2-mineru`。

## M2：独立纯解析网关

现有 OMP 19091 服务包含故障/参数专项处理和业务回调，本工具不再直接接入该业务提交入口。新网关位于 [gateway/](gateway/README.md)，代码、环境、认证、数据库、文件和启动进程均独立，不导入或修改 OMP 项目。

```text
本机网页 → 本机 API/Worker → Windows 新网关 19092 → 回环 MinerU API 58666
现有 OMP → 19091 → 现有 MinerU CLI / 专项处理 / 回调（保持原样）
```

- [Windows 部署与启动说明](gateway/README.md)：独立安装、原生接口只读核实、启动、认证检查、异常恢复与回滚。
- [隔离方案与资源边界](docs/mineru-service-isolation.md)：新网关串行处理不代表整机全局串行，共用 GPU 的性能隔离仍需资源或运行窗口安排。
- [本轮开发测试摘要](docs/test-reports/2026-10-24-m2-gateway.md)：区分离线测试、本机真实 HTTP 冒烟和真实引擎验收。

Windows 先运行 `gateway/windows/setup.ps1` 和 `check-upstream.ps1`，后者只读取 **Windows 本机** 58666 的 OpenAPI/health；接口或版本不符则停止。核实通过后按部署说明配置独立网关并启动 `start.ps1`。Mac 无法直接读取 Windows 回环监听，不能以官方源码或模拟响应替代实际实例检查。

配置 Mac 本地 `.env`（不入库）：

~~~dotenv
MINERU_MODE=remote
MINERU_BASE_URL=http://<Windows-host>:19092
MINERU_API_KEY=<独立网关生成的 GATEWAY_TOKEN>
MINERU_PARSE_METHOD=auto
MINERU_POLL_TIMEOUT=900
~~~

原生协议适配器先核实 OpenAPI，优先异步 `/tasks`，兼容实际声明的原生 `/file_parse` 同步入口。独立网关目前仅支持经过核实的原生异步 API，固定请求原始 Markdown 和结构化 JSON，不执行专用业务后处理，也不向其他主机转发密钥或跟随上游链接。

重启本机 API/Worker/前端后执行：

~~~sh
uv run python scripts/probe_mineru.py
uv run python scripts/live_smoke.py --pdf tests/fixtures/live-text.pdf --expect ORCHID-4827
uv run python scripts/live_smoke.py --pdf tests/fixtures/live-scan.pdf --expect ORCHID-4827
~~~

真实验收脚本先检查工作模式和接口，成功才上传；报告保存在忽略的 `.local/live-smoke.json`，两次执行会覆盖该文件，需分别保留本地结果。还应按 [样例核对清单](tests/fixtures/README.md) 检查两页中文、章节和表格单元格；单个关键字命中不足以证明转换准确率。真实输出、耗时和 OCR 质量尚未取得时不得宣称通过。

生成可复制的独立 Windows 源码部署包（不含 Python、uv、模型或离线依赖）：

~~~sh
uv run python scripts/package_gateway.py
~~~

输出 `.local/pdf2markdown-gateway-windows.zip`；CI 也提供同名部署 artifact。包内仅有公开源码、锁文件、模板、Windows 脚本和哈希清单，不包含本地配置及运行数据。

## 本机启动

需要 Python 3.12（可由 uv 自动安装）、Node.js 24 LTS 和 npm。先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，Node 版本可使用 `.nvmrc` 管理。

~~~sh
uv sync --locked
npm --prefix frontend ci
uv run python scripts/dev.py
~~~

打开 http://127.0.0.1:5173/ 。API 位于 http://127.0.0.1:8000/api/health，接口文档位于 http://127.0.0.1:8000/docs。

启动命令会一起运行 API、独立 Worker 和前端；按 Ctrl+C 一并停止。默认仅绑定本机回环地址。该启动脚本当前面向 macOS/Linux，Windows 服务部署留待后续阶段。

端口占用时可使用 `uv run python scripts/dev.py --api-port 8010 --web-port 5180`。没有 `.env` 时默认 Mock；真实模式按上面的配置启动。网页顶部显示当前模式和服务检测结果；历史任务保留创建时的模式，远程失败不会回退到 Mock。

### 使用流程

1. 上传 PDF，或点击“先用示例体验一下”。单文件默认最多 20 MB、200 页，拒绝损坏或加密 PDF。
2. Worker 在后台处理；侧栏保存最近 100 个任务。服务重启后，已完成内容仍保留，中断任务标记失败并允许重试。
3. 在源码编辑框中修改 Markdown，右侧阅读预览即时更新。
4. 调整分隔符、目标字符数和来源文件说明，点击“保存并更新分块”。未保存时分块面板会提示其来自已保存版本；M2 仍不伪造精确块级页码。
5. 下载阅读版或知识库版。下载前自动保存当前修改；版本冲突或分隔符冲突会阻止覆盖与导出并显示错误。

Mock 对任何有效 PDF 返回同一份固定示例，不提取 PDF 正文。remote 模式只接受实际服务返回的内容，当前指定网关尚未联调成功。原始 PDF 可通过“原始 PDF”打开；内嵌 PDF 对照和 Monaco 编辑器留待 M4。

真实解析产物计划保存到 `data/<task-id>/artifacts/`：`raw.json` 保留原响应，`document.json` 保存统一结构与原始字段，`original.md` 保留未编辑正文。已有 M1 数据库自动增加所需列，不删除任务或已保存内容。

异步任务 ID 在查询前持久化；Worker 重启后继续查询已有任务。查询超时可重试续查，提交结果不确定或任务已过期时需用户明确确认重提。只缓存成功解析的原始结果，不缓存人工编辑；缓存键包含文件哈希、服务来源、已知版本、接口指纹、参数、认证作用域摘要及可配置命名空间。服务版本未知时禁用缓存；更换模型但版本不变时应更新 `MINERU_CACHE_NAMESPACE`。

M2 保留上游 HTML 表格并在预览中安全渲染；HTML→Markdown 表格规范化、长表切分、续表与语义复核属于 M3。图片引用不会自动加载，独立 `.md` 不携带图片文件，出现引用时显示限制说明。若服务只返回 Markdown，会明确标注缺少结构化信息。

### 本机验证

~~~sh
uv run pytest -q
npm --prefix frontend test
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npm run test:e2e
~~~

浏览器测试自动使用 5174/8001 端口、Mock 工作模式和临时数据目录，不复用预览工作区。远程状态 UI 测试使用明确的 API 模拟，并非真实 OCR 验收。机器已有 Microsoft Edge 时也可用 `PLAYWRIGHT_CHANNEL=msedge npm run test:e2e`。自动检查工作流见 `.github/workflows/ci.yml`；真实服务验收需单独运行。

`.tools/` 若存在，仅用于当前开发机的工具引导，不是项目依赖，不提交仓库。项目环境使用 `uv.lock` 和 `frontend/package-lock.json`；启动脚本不会更换系统 Python。

## 范围

- 支持文本型、扫描型和混合型 PDF，复用外部 MinerU 3.1.1 服务。
- 保留标题层级、正文、列表和表格，结合位置与重复模式清理页眉、页脚和页码。
- 按章节及完整内容单元生成知识块，保留章节路径，可选附带来源页码。
- 支持自定义分隔符、目标块大小、长表按行分块和重复表头。
- 提供 PDF 对照、Markdown 源码编辑、渲染预览、分块预览。
- 导出连续阅读版 `.md` 和知识库分块版 `.chunked.md`。
- 不连接 FastGPT 服务器，不要求 FastGPT API Key，不在本机安装 MinerU 模型。

## 本机开发架构

浏览器 → 本机 Vue 前端 → 本机 FastAPI → Windows 上的 MinerU 外部服务。

- 前端：Vue 3、TypeScript、Vite；M1 使用原生文本编辑框和安全 Markdown 渲染，PDF.js 对照、Monaco 属于后续增强。
- 后端：Python 3.12、FastAPI、HTTPX；SQLite 保存任务和编辑版本。
- 任务执行：独立单 Worker，使用 SQLite 持久化队列；API 请求不等待整份 PDF 解析完成。
- 本地文件：保存在忽略提交的 `data/` 目录，记录原始 PDF、解析产物和编辑结果。
- 开发端口暂定前端 `127.0.0.1:5173`、API `127.0.0.1:8000`，占用时可配置。
- 首期无需 Docker、Redis、Celery；后续按并发与部署需要扩展。

项目使用 Python 3.12 和 Node.js 24 LTS，依赖通过 `uv.lock`、`frontend/package-lock.json` 锁定。

## MinerU 接入

- 外部服务地址通过本地环境变量配置，不在代码中写死。
- MinerU 3.1.1 使用 3.x 接口适配，不能直接套用 4.x `/v1/...` 接口。
- `uvicorn app:app` 只说明应用启动方式，不代表外部服务已经代理原生 `/tasks`、状态查询和结果下载。
- 联调前检查外部服务 OpenAPI 或 `app.py`，核对请求字段、认证、任务状态、返回格式和结果获取方式。
- 优先使用上游异步任务接口；如网关仅有同步解析，则由本机 Worker 调用并持久化状态。
- 必须获取 Markdown 和可用的结构化 JSON；仅有 Markdown 时明确提示来源定位、跨页处理能力受限。
- Windows 本地文件路径和回环地址不能直接交给本机读取，需通过网关返回内容或下载资源。
- 分别记录本机任务 ID 与上游任务 ID；状态查询超时后保留上游 ID，防止盲目重复提交。
- API/Worker 重启后识别中断任务，能够恢复查询或显式标记待重试，避免长期停留在处理中。

本地配置规划：`MINERU_BASE_URL`、`MINERU_API_KEY`（可选）、`MINERU_MODE=mock|remote`、`DATA_DIR`、请求超时和并发上限。只提交无凭据的 `.env.example`；真实配置保存在被忽略的 `.env`。

## 处理流水线

1. 校验上传文件类型、大小、PDF 可读性及页数；加密文件给出明确提示。
2. 创建持久化任务，提交或调用 MinerU，保存原始解析结果。
3. 将不同产物映射为内部文档结构，保留页号、原始块 ID、阅读顺序和可用的坐标。
4. 保守清洗排版换行、页眉页脚和页码，恢复章节路径；不全局去重正文，不改写金额或编号。
5. 优先保留 MinerU 已合并的表格，对疑似续表补充判断和人工复核。
6. 按章节、段落、条款、列表和表格生成块，超长内容在自然边界继续细分。
7. 预览、编辑和重新分块，保留用户编辑版本。
8. 导出 UTF-8 Markdown；参数变化只重跑后处理，不重复 OCR。

解析缓存键包含文件哈希、MinerU 版本和解析配置；后处理缓存另外包含规则版本及分块参数。

## 分块与表格约定

- 默认分隔符拟为 `<<<FASTGPT_CHUNK>>>`，独占一行；检查与原文冲突，不插入首尾空块。
- 同一块优先保留完整主题；列表引导句与列表、表名与表格尽量一起保留。
- 初始正文目标范围建议 600–1200 个中文字符，可配置；字符数与 token 估计分别显示。
- 每块重复章节路径；页码默认采用 PDF 实际页序，从 1 开始，对上游零基页号只转换一次。
- 表格块重复表名、表头、单位和适用注释；按完整行或关联行组拆分。
- 跨页表合并综合相邻页位置、列结构、表头、表名和续表标记；不能只看列数。
- 多级表头展开为完整列名；跨行类别补充到相关行。无法可靠表示的复杂表保留原表对照并提示复核。
- 转义单元格中的管道符，处理单元格换行，保留数字、单位和脚注关系。
- 人工编辑导致原文映射不再精确时，标记已修改，不伪造精确来源位置。
- Markdown/HTML 预览需清理不可信 HTML，避免文档中的脚本执行。

## 目录

~~~text
frontend/                 网页与交互测试
backend/app/api/          上传、任务、编辑及下载 API
backend/app/mineru/       MinerU 适配与产物规范化
backend/app/processing/   清洗、表格、分块和导出
backend/app/worker/       持久化任务执行
backend/tests/            后端和结构处理回归测试
tests/fixtures/           可公开的合成样例和预期结果
frontend/tests/e2e/       浏览器端到端测试
docs/test-reports/        脱敏后的阶段测试摘要
data/                    本地运行数据，不提交
~~~

## 开发里程碑

| 阶段 | 交付 | 验收 |
| --- | --- | --- |
| M1 基础闭环 | 已实现：工程、Mock、上传、持久化任务、编辑预览、基础分块、两种下载 | 离线单元及端到端验证，结果见阶段测试摘要 |
| M2 MinerU 联调 | 已实现原生适配、独立 19092 网关及 Windows 部署文件；目标 58666 待核实和新网关待部署 | 真实服务验收受阻，文本和扫描 PDF 尚未取得真实输出 |
| M3 结构与分块 | 标题上下文、清洗、列表保护、表格转换、长表分块及续表复核 | 合成样例覆盖内容丢失、顺序、表头、页码和分隔符边界 |
| M4 完整验收 | PDF 对照、编辑来源标记、重启恢复、回归、启动说明 | 本机浏览器完整流程通过，报告性能和已知限制 |

Mock 模式必须在网页上明确标识，不将其输出当作真实 PDF 解析结果。真实解析联调未通过时，不宣称 OCR 或表格识别已验收。

## 测试方案

离线自动回归不依赖 MinerU 网络：

- Python：pytest + FastAPI TestClient/HTTPX，验证上传、持久化状态、重试、结果和下载。
- 结构处理：合成 JSON/HTML 验证章节、阅读顺序、重复页眉、数字保留、续表合并和误合并。
- 分块：验证分隔符冲突、章节边界、列表引导句、长表表头、页码及编辑结果导出一致性。
- 前端：Vitest 测试关键状态与参数；Playwright 覆盖上传 → 编辑 → 分块 → 下载。
- CI：后续在 GitHub Actions 中执行后端测试、前端类型检查/测试/构建和 Mock 端到端测试。

真实服务测试单独执行：

- 文本、扫描、混合页、双栏、跨页表及多级表头 PDF。
- 网络中断、服务不可达、任务失败、重复文件、后端重启。
- 记录文件页数、大小、解析配置、排队/解析/后处理耗时，以及人工确认的内容和表格问题。
- 检查原文数字、单位、编号、条款和上下文，不用块数或字符数代替准确性评估。

真实联调测试可在服务不可达时明确跳过，但报告必须区分通过、失败、跳过和未执行。性能在现有硬件实测后报告，不预先承诺秒数或识别准确率。

## Git 与交付约定

- 唯一远程仓库：https://github.com/lee3037/pdf2markdown.git。
- 初始化文档提交到 `main`；后续每个可验收的小阶段运行相关检查，再提交并推送。
- 日常小阶段使用 `main`；较大的独立工作可使用 `feat/<topic>` 分支并推送，交付时明确分支。
- 代码、必要测试、依赖锁文件、迁移和使用文档一起提交。
- 每阶段在 `docs/test-reports/` 保存脱敏摘要：日期、范围、环境、命令、结果和已知限制；注明与报告同一提交或对应代码提交。
- 失败的测试如需保存工作进度，明确以 WIP 标记并记录原因，不称其为可验收版本。
- 不提交真实业务 PDF、解析全文、运行数据库、凭据、`.env`、原始日志或包含业务内容的截图。
- 测试样例只使用合成或明确可公开的数据；原始运行报告可保留本地，只提交整理后的摘要。
- 每轮交付报告提交 SHA、分支、推送结果及验证结果；推送失败不得声称已同步。

## 参考

- [Node.js 官方版本状态](https://nodejs.org/en/about/previous-releases)
- [Vite 官方指南](https://vite.dev/guide/)
- [FastAPI 官方测试指南](https://fastapi.tiangolo.com/tutorial/testing/)
- [MinerU 3.1.1 发布说明](https://pypi.org/project/mineru/3.1.1/)
