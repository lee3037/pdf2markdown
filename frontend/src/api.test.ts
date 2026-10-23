import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());
it("shows server validation errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "分隔符与正文冲突" }), {
          status: 422,
        }),
      ),
  );
  await expect(api("/tasks")).rejects.toThrow("分隔符与正文冲突");
});
it("explains a disconnected local backend", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
  await expect(api("/health")).rejects.toThrow("无法连接本机后端");
});
