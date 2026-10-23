// API simulations exercise UI states; these do not constitute live MinerU acceptance.
import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";

async function remoteAPI(page: Page, success: boolean) {
  let uploaded = false;
  const task = {
    id: "simulated-remote",
    filename: "sample.pdf",
    pages: 1,
    size: 700,
    mode: "remote",
    status: success ? "completed" : "failed",
    stage: success ? "真实解析完成" : "处理失败",
    progress: success ? 100 : 15,
    created_at: "2026-10-23T00:00:00Z",
    updated_at: "2026-10-23T00:00:00Z",
    markdown: success
      ? "# Invoice\n\n<table><tr><th>费用</th><th>单位</th></tr><tr><td>100.50</td><td>元</td></tr></table>"
      : null,
    settings: {
      separator: "<<<FASTGPT_CHUNK>>>",
      target_size: 800,
      include_source: false,
    },
    revision: success ? 1 : 0,
    edited: false,
    error: success
      ? null
      : "未收到解析服务的有效 HTTP 响应，请检查网络、网关和服务日志。",
    error_code: success ? null : "connection_failed",
    upstream_id: success ? "upstream-1" : null,
    submission_started: false,
    metadata: success
      ? {
          producer_version: "3.1.1",
          backend: "pipeline",
          structured: true,
          block_count: 1,
          cached: true,
          warnings: [
            "表格保留 MinerU 原始 HTML；Markdown 表格规范化与跨页复核将在 M3 完成。",
          ],
        }
      : {},
    chunks: [],
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === "/api/health")
      body = { mode: "remote", max_upload_mb: 20, max_pdf_pages: 200 };
    else if (path === "/api/mineru/status")
      body = {
        available: success,
        mode: "remote",
        version: "3.1.1",
        style: "async",
        message: success
          ? "接口契约已核实。"
          : "未收到解析服务的有效 HTTP 响应。",
      };
    else if (path === "/api/tasks" && route.request().method() === "POST") {
      uploaded = true;
      body = task;
    } else if (path === "/api/tasks") body = uploaded ? [task] : [];
    else body = task;
    await route.fulfill({ json: body });
  });
}

test("simulated remote failure stays failed without replacing the PDF with Mock output", async ({
  page,
}) => {
  await remoteAPI(page, false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByText("M2 · MinerU 远程解析", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("解析服务尚不可用", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("上传 PDF")
    .setInputFiles(resolve("../tests/fixtures/sample.pdf"));
  await expect(page.getByRole("heading", { name: "处理失败" })).toBeVisible();
  await expect(
    page.getByText(
      "未收到解析服务的有效 HTTP 响应，请检查网络、网关和服务日志。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Markdown 源码" }),
  ).toHaveCount(0);
  await expect(page.getByText("Mock 示例输出", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("simulated native result shows HTML table, cache and structured-output warnings", async ({
  page,
}) => {
  await remoteAPI(page, true);
  await page.goto("/");
  await page
    .getByLabel("上传 PDF")
    .setInputFiles(resolve("../tests/fixtures/sample.pdf"));
  await expect(
    page.getByRole("textbox", { name: "Markdown 源码" }),
  ).toHaveValue(/100.50/);
  await expect(page.locator(".rendered table")).toBeVisible();
  await expect(page.locator(".rendered td").first()).toHaveText("100.50");
  await expect(page.getByText("复用解析缓存", { exact: false })).toBeVisible();
  await expect(page.locator(".result-info")).toContainText("结构化结果已保留");
  await expect(page.locator(".result-info")).toContainText(
    "Markdown 表格规范化与跨页复核将在 M3 完成",
  );
});
