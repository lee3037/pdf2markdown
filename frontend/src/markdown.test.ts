import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("Markdown preview", () => {
  it("renders headings, lists and tables", () => {
    const result = renderMarkdown(
      "# 标题\n\n1. 材料\n\n| 价格 | 单位 |\n| --- | --- |\n| 100 | 元 |",
    );
    expect(result).toContain("<h1>标题</h1>");
    expect(result).toContain("<ol>");
    expect(result).toContain("<table>");
  });
  it("does not execute raw HTML or javascript links", () => {
    const result = renderMarkdown(
      "<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[link](javascript:alert(1))",
    );
    expect(result).not.toContain("<script>");
    expect(result).not.toContain("<img");
    expect(result).not.toContain('href="javascript:');
  });
  it("does not load remote images from document content", () => {
    expect(
      renderMarkdown("![private](https://example.com/track)"),
    ).not.toContain("<img");
  });
  it("renders native HTML tables without retaining executable attributes or CSS fetches", () => {
    const html = renderMarkdown(
      '<table><tr><th colspan="2">费用</th></tr><tr><td style="background:url(https://example.com/track)" onclick="alert(1)">100.50</td><td>元</td></tr></table>',
    );
    expect(html).toContain("<table>");
    expect(html).toContain('colspan="2"');
    expect(html).toContain("100.50");
    expect(html).not.toContain("style=");
    expect(html).not.toContain("onclick");
    expect(html).not.toContain("https://example.com/track");
  });
});
