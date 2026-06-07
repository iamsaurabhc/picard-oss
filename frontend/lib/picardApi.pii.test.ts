import { describe, expect, it, vi, beforeEach } from "vitest";

describe("streamChat PII flag", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("includes enable_pii_protection in request body", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: done\ndata: {}\n\n"));
        controller.close();
      },
    });
    vi.mocked(fetch).mockResolvedValue(
      new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } })
    );

    const { picardApi } = await import("./picardApi");
    const gen = picardApi.streamChat({
      session_id: "s1",
      workspace_id: "w1",
      message: "hello",
      enable_pii_protection: true,
    });
    await gen.next();

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body));
    expect(body.enable_pii_protection).toBe(true);
  });
});
