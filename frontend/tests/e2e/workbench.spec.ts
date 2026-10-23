import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

test("upload, edit, rechunk, download both versions and reopen persisted work", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByText("M2 · Mock 演示模式", { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/m1-home.png", fullPage: true });
  await page
    .getByLabel("上传 PDF")
    .setInputFiles(resolve("../tests/fixtures/sample.pdf"));
  const editor = page.getByRole("textbox", { name: "Markdown 源码" });
  await expect(editor).toBeVisible();
  await expect(editor).toHaveValue(/固定示例/);
  const draft =
    "# 本机测试\n\n## 第一章\n\n准确保留金额 100.50 元及编号 A-01。\n\n## 第二章\n\n另一条完整内容。\n";
  await editor.fill(draft);
  await expect(page.locator(".rendered")).toContainText(
    "准确保留金额 100.50 元",
  );
  await page.getByRole("button", { name: /分块预览/ }).click();
  await expect(
    page.getByText("当前分块来自已保存版本。", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "分隔符", exact: true })
    .fill("===KNOWLEDGE===");
  await page.getByRole("spinbutton", { name: "目标字符数" }).fill("100");
  await page.getByRole("button", { name: "保存并更新分块" }).click();
  await expect(page.getByRole("status")).toHaveText("已保存并更新分块");
  await expect(page.locator(".chunk-card")).toHaveCount(2);
  await page.screenshot({ path: "test-results/m1-editor.png", fullPage: true });
  for (const [name, suffix] of [
    ["阅读版", ".md"],
    ["知识库版", ".chunked.md"],
  ] as const) {
    const event = page.waitForEvent("download");
    await page.getByRole("button", { name, exact: true }).click();
    const download = await event;
    expect(download.suggestedFilename()).toBe("sample" + suffix);
    const content = await readFile((await download.path())!, "utf8");
    if (suffix === ".md") expect(content).toBe(draft);
    else {
      expect(content.split("===KNOWLEDGE===")).toHaveLength(2);
      expect(content).toContain("100.50 元及编号 A-01");
      expect(content.match(/# 本机测试/g)).toHaveLength(2);
    }
  }
  await page.reload();
  await page
    .getByRole("button", { name: /sample.pdf/ })
    .first()
    .click();
  await expect(editor).toHaveValue(draft);
  await expect(
    page.getByRole("textbox", { name: "分隔符", exact: true }),
  ).toHaveValue("===KNOWLEDGE===");
  expect(errors).toEqual([]);
});

test("delimiter conflict leaves the editor and saved data intact", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "先用示例体验一下" }).click();
  const editor = page.getByRole("textbox", { name: "Markdown 源码" });
  await expect(editor).toBeVisible();
  const original = await editor.inputValue();
  await editor.fill(original + "\n\nCONFLICT");
  await page
    .getByRole("textbox", { name: "分隔符", exact: true })
    .fill("CONFLICT");
  await page.getByRole("button", { name: "保存并更新分块" }).click();
  await expect(page.getByRole("alert")).toContainText("分隔符与正文冲突");
  await expect(editor).toHaveValue(original + "\n\nCONFLICT");
});

test("mobile upload screen fits the viewport and rejects unsupported files", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "选择 PDF 文件" }),
  ).toBeVisible();
  await page.getByLabel("上传 PDF").setInputFiles({
    name: "bad.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("not pdf"),
  });
  await expect(page.getByRole("alert")).toContainText("请选择 PDF 文件");
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits).toBe(true);
  await page.getByRole("button", { name: "先用示例体验一下" }).click();
  await expect(
    page.getByRole("textbox", { name: "Markdown 源码" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("download saves the latest unsaved edits", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "先用示例体验一下" }).click();
  const editor = page.getByRole("textbox", { name: "Markdown 源码" });
  await expect(editor).toBeVisible();
  const draft = "# 最新版本\n\n未手动保存的修改也必须进入下载文件。\n";
  await editor.fill(draft);
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name: "阅读版", exact: true }).click();
  const result = await event;
  expect(await readFile((await result.path())!, "utf8")).toBe(draft);
  await expect(page.locator(".editor-state")).toContainText("全部修改已保存");
});
