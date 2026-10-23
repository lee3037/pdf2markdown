# 项目协作约定

## 已确认的产品范围

- 先在当前本机开发与测试，提供独立 PDF 转 Markdown 网页工具。
- 复用远程 Windows MinerU 3.1.1。外部服务由自定义 app.py 提供，真实接口必须先核实。
- 不连接 FastGPT 服务器，不要求 FastGPT 凭据；仅提供预览、编辑、分块和 Markdown 下载。
- 真实服务配置放在本地 .env，不把主机地址或凭据写入前端构建产物。
- 用户已要求后续开发与测试工作提交并推送至 https://github.com/lee3037/pdf2markdown.git。

## 开发与交付

- 按 README.md 的里程碑推进，所有规划功能在实现和验证前均不得声称已完成。
- 每轮完成相关代码、必要回归与文档后，执行相关检查，提交并推送到上述仓库；正常推送无需反复请求用户确认。
- 每轮交付说明分支、提交 SHA、检查结果、推送状态及未完成项。
- 相关测试未通过时如需推送进度，标记 WIP，并记录实际失败或阻塞；不得伪称通过。
- 真实 MinerU 不可达时继续离线回归，单独报告真实解析尚未验证；Mock 模式必须明显标识。
- 测试代码和可公开样例进入仓库；在 docs/test-reports/ 保存脱敏测试摘要，真实业务文档、产物和原始日志只保存在本地。
- 不提交 .env、密钥、运行数据库、真实上传 PDF、原始解析全文或含业务内容的截图。
- 先保护原文和表格语义，无法可靠识别或合并时标记复核，不静默编造内容。
- 项目环境采用独立 Python 虚拟环境和锁文件，不替换操作系统 Python。

<!-- codebase-memory-mcp:start -->
# Codebase Knowledge Graph (codebase-memory-mcp)

This project uses codebase-memory-mcp to maintain a knowledge graph of the codebase.
ALWAYS prefer MCP graph tools over grep/glob/file-search for code discovery.

## Priority Order
1. `search_graph` — find functions, classes, routes, variables by pattern
2. `trace_path` — trace who calls a function or what it calls
3. `get_code_snippet` — read specific function/class source code
4. `query_graph` — run Cypher queries for complex patterns
5. `get_architecture` — high-level project summary

## When to fall back to grep/glob
- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- When MCP tools return insufficient results

## Examples
- Find a handler: `search_graph(name_pattern=".*OrderHandler.*")`
- Who calls it: `trace_path(function_name="OrderHandler", direction="inbound")`
- Read source: `get_code_snippet(qualified_name="pkg/orders.OrderHandler")`
<!-- codebase-memory-mcp:end -->

If graph tools are unavailable in the current session, report that limitation briefly and fall back to rg for code discovery.
