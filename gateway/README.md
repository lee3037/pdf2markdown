# 独立 19092 纯解析网关

本目录可单独复制到 Windows，默认只监听 `127.0.0.1:19092`，固定对接 Windows 回环上的原生 MinerU API。它不导入 OMP 服务，不执行故障/参数专项提取、业务回调、MinIO 上传或 FastGPT 同步。不会安装 MinerU/模型，也不改变现有 19091 或 58666 的配置。

**当前开发已通过离线模拟测试，尚未在目标 Windows 上运行或完成真实解析验收。** Mac 无法核实只监听 Windows 回环的 58666；以下 preflight 必须在 Windows 本机执行。实际响应不兼容时停止，不猜测接口。

## 1. 放置文件和安装独立环境

将 `gateway/` 的内容（或生成的 Windows ZIP）放到新的目录，例如：

```text
D:\services\pdf2markdown-gateway\
  pyproject.toml
  uv.lock
  .env.example
  pure_gateway\
  windows\
```

不要覆盖原来的 `omp-doc-convert` 目录。部署包不包含 `.env`、数据库、上传文件、模型、原始日志或已有项目源码；`MANIFEST.sha256.json` 可核对公开文件哈希。

Windows 需要 uv（开发/CI 使用 0.13.5）。可使用 [uv 官方安装方法](https://docs.astral.sh/uv/getting-started/installation/)；不在原有 Anaconda 环境中安装依赖。以下 setup 使用锁文件、Python 3.12 和当前目录独立 `.venv`，不会更换系统 Python，也不会使用既有 MinerU 虚拟环境。

```powershell
cd D:\services\pdf2markdown-gateway
.\windows\setup.ps1
```

如 uv 不在 PATH：`.\windows\setup.ps1 -UvPath C:\path\to\uv.exe`。setup 自动生成新的随机 `GATEWAY_TOKEN` 到本目录 `.env`，不打印密钥，且不覆盖已有 `.env`。

如果本机策略不允许运行脚本，可按部署方策略操作，或执行等价的命令（独立目录且未设置其他 `UV_PROJECT_ENVIRONMENT` 时）：

```powershell
uv sync --project . --python 3.12 --locked --no-dev
.\.venv\Scripts\python.exe -m pure_gateway.init_config
```

## 2. 先核实 58666，再启动新服务

```powershell
.\windows\check-upstream.ps1
```

等价命令：

```powershell
.\.venv\Scripts\python.exe -m pure_gateway.probe --save-schema .local\upstream-openapi.json
```

该命令只请求 `/openapi.json` 与 `/health`，不上传文件。要求实际实例公开原生异步 `/tasks`、状态和结果查询，上传为 binary files 数组，并支持 Markdown、Middle JSON、Content List 和 JSON 输出；兼容 `format=binary` 及 OpenAPI 的 `contentMediaType=application/octet-stream` 声明。健康状态须为 healthy，版本默认须精确为 3.1.1。成功时输出 `available=true`、版本、协议、接口字段和指纹，原始契约只保存在忽略的 `.local/`。

若失败，先提供这份本机检查的脱敏结果用于适配，不修改 19091，不要求将 58666 改为对外监听。默认仅支持原生异步 API；未实现同步专用部署的兜底。

核实通过后编辑本目录 `.env`，将 `GATEWAY_HOST` 改为 `0.0.0.0` 才能从 Mac 访问；Windows 防火墙只放行获准 Mac/网络来源到 **19092**。不需要新增到 58666 的远程访问，也不调整 19091 的规则。然后启动：

```powershell
.\windows\start.ps1
```

start 会先检查 19092 是否占用，再执行原生 preflight；失败则停止，绝不结束占用端口的进程。等价启动命令为 `.\.venv\Scripts\python.exe -m pure_gateway.serve`，它只允许端口 19092、一个进程，并用数据目录文件锁防止多个 Worker 同时处理。

另开一个 PowerShell，在同一目录运行：

```powershell
.\.venv\Scripts\python.exe -m pure_gateway.check
```

它从本地配置读取认证，不打印 token。预期 HTTP 200、status=healthy、version=3.1.1。未带 Bearer token 请求健康检查/OpenAPI/任务接口返回 401 是预期保护，不代表服务不可用。

需要常驻时，可由部署方使用已有的服务管理器注册**新的**服务，例如 `pdf2markdown-gateway`：程序为本目录 `.venv\Scripts\python.exe`，参数 `-m pure_gateway.serve`，工作目录为本目录。先完成前台核验；本包不自动注册服务、改执行策略、改防火墙或重启旧服务。

## 3. 连接本机小工具

在 Mac 的 pdf2markdown 项目 `.env` 中设置（实际值不入库）：

```dotenv
MINERU_MODE=remote
MINERU_BASE_URL=http://<Windows-host>:19092
MINERU_API_KEY=<本次生成的 GATEWAY_TOKEN>
MINERU_PARSE_METHOD=auto
```

通过安全方式将 token 写入本机配置，不在聊天、命令行参数、截图或公开日志中展示。两端无需 OMP 提交密钥或 FastGPT 凭据。重启本机 API/Worker，先运行 `uv run python scripts/probe_mineru.py`，通过后再进行真实 PDF 测试。

网关的 backend 在 Windows `.env` 的 `GATEWAY_BACKEND` 设置，留空则保留上游默认值。客户端不能指定其他解析服务器 URL、业务回调或远程 backend；额外表单字段不会转发。更换模型或服务配置且版本未变时增加 `GATEWAY_CACHE_NAMESPACE`；网关配置和上游接口指纹参与本工具缓存隔离。

## 4. 任务语义、隔离与恢复

- 每次只接受一个有效、未加密 PDF，默认限制 20 MB / 200 页，含处理中的待完成任务最多 4 个；满额返回 429。HTTP 请求体另有有限的表单开销额度，chunked 请求也受大小限制。
- 本地随机任务 ID、独立 SQLite、文件目录与原生任务映射持久化。API 不提供任意原生任务 ID 的透传查询，Bearer token 不发送到上游；所有上游 URL 固定为配置的回环地址，禁止 19091/19092、远程地址和重定向。
- 固定请求原始 Markdown 与结构化 JSON，不处理正文含义，不上传图片。保存返回的原始结果；空正文、版本不匹配或超限结果明确失败，不产生 Mock 正文。
- 单个串行 Worker 提交到原生 API，并保持原任务查询到终态后才处理下一任务；查询暂时断开保留已知上游 ID。重启继续查询，不重复上传。
- 如果原生 POST 超时、返回不确定响应，或网关在提交后尚未保存上游 ID 时崩溃，记录 `submission_uncertain`，停止新任务及后续排队任务的提交。管理员必须核实上游状态；不自动认为失败就重新上传。
- 可在停止**新网关**后运行 `python -m pure_gateway.manage list` 检查脱敏状态。确认上游已无该不确定任务在运行、且接受不能自动找回其结果后，才执行 `python -m pure_gateway.manage resolve-uncertain <网关任务ID> --confirmed-upstream-idle`。该命令只解除保护，不重提、不删除产物；之后由使用者明确选择是否新建/重试任务。不要停止旧 OMP 服务来做此操作。
- 成功、失败的文件和记录都保留在 `GATEWAY_DATA_DIR`，当前没有自动过期删除。运维需在服务停止后按自身留存策略备份/清理本网关目录；不清理原生 API 或 OMP 的文件。

单网关并发 1 **不等于整机并发 1**。OMP CLI、原生 API 的其他客户端仍可能竞争 GPU/显存。首次真实测试应在约定互斥窗口执行；严格性能隔离需要独立 GPU/机器。本网关不修改旧服务来建立全局锁。

## 5. 验收与回滚

在 Mac 启动小工具后：

```sh
uv run python scripts/live_smoke.py --pdf tests/fixtures/live-text.pdf --expect ORCHID-4827
uv run python scripts/live_smoke.py --pdf tests/fixtures/live-scan.pdf --expect ORCHID-4827
```

脚本的关键字检查是最小自动门槛，仍需按 `tests/fixtures/README.md` 核对两页中文、章节顺序、第二页标识、表头及每行数值，再核对网页编辑、分块和两种下载。只有取得实际输出后才记录真实耗时和准确性；离线引擎模拟测试不能替代此验收。

回滚只停止新网关进程或新注册的服务，并恢复本工具的本地连接配置；本次没有任何需要回滚的 19091 变更。后续 M3 表格规范化/长表/跨页处理不在网关内实现。
