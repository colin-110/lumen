import { beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat, ApiError } from "./api-client";
import type { ChatSource, LLMError } from "./types";

/** Builds a Response whose body streams the given chunks, so the SSE parser
 * can be tested against frames that arrive split across network reads — the
 * case that breaks naive line-by-line parsers. */
function sseResponse(chunks: string[], ok = true, status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return { ok, status, body: stream, statusText: "OK", json: async () => ({}) } as unknown as Response;
}

const frame = (type: string, data: unknown) => `data: ${JSON.stringify({ type, data })}\n\n`;

/** A fetch mock whose calls stay typed, so assertions on the request body and
 * headers don't need a cast in every test. */
function makeFetchMock() {
  // Params are declared purely to type mock.calls[i][1] as RequestInit.
  return vi.fn((...args: [string, RequestInit]) => {
    void args;
    return Promise.resolve(sseResponse(["data: [DONE]\n\n"]));
  });
}
const initOf = (m: ReturnType<typeof makeFetchMock>, i: number): RequestInit => m.mock.calls[i][1];
const bodyOf = (m: ReturnType<typeof makeFetchMock>, i: number): Record<string, unknown> =>
  JSON.parse(String(initOf(m, i).body));

describe("streamChat SSE parsing", () => {
  beforeEach(() => localStorage.setItem("lumen_access_token", "test-token"));

  it("delivers tokens in order", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse([frame("token", "Hello "), frame("token", "world"), "data: [DONE]\n\n"]))
    );
    const tokens: string[] = [];
    await streamChat("q", undefined, { onToken: (t) => tokens.push(t) });
    expect(tokens.join("")).toBe("Hello world");
  });

  it("reassembles a frame split across two network reads", async () => {
    // The killer case: one SSE frame arriving in two pieces.
    const whole = frame("token", "split-safely");
    const cut = Math.floor(whole.length / 2);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse([whole.slice(0, cut), whole.slice(cut), "data: [DONE]\n\n"]))
    );
    const tokens: string[] = [];
    await streamChat("q", undefined, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["split-safely"]);
  });

  it("surfaces the conversation id so a new chat can adopt it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse([frame("conversation", { conversation_id: "conv-42" })]))
    );
    const ids: string[] = [];
    await streamChat("q", undefined, { onConversation: (id) => ids.push(id) });
    expect(ids).toEqual(["conv-42"]);
  });

  it("passes sources through", async () => {
    const sources: ChatSource[] = [
      { filename: "a.pdf", document_id: "d1", chunk_id: "c1", score: 1.5, snippet: "..." },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([frame("sources", sources)])));
    let received: ChatSource[] = [];
    await streamChat("q", undefined, { onSources: (s) => (received = s) });
    expect(received).toHaveLength(1);
    expect(received[0].filename).toBe("a.pdf");
  });

  it("delivers a structured quota error rather than a bare string", async () => {
    const err: LLMError = {
      kind: "quota",
      message: "quota used up",
      retry_after_seconds: 38,
      retryable: false,
      detail: "RESOURCE_EXHAUSTED",
    };
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([frame("error", err)])));
    let got: LLMError | string | undefined;
    await streamChat("q", undefined, { onError: (e) => (got = e) });
    expect(typeof got).toBe("object");
    expect((got as LLMError).kind).toBe("quota");
    expect((got as LLMError).retry_after_seconds).toBe(38);
  });

  it("still accepts a legacy string error from an older backend", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([frame("error", "something broke")])));
    let got: LLMError | string | undefined;
    await streamChat("q", undefined, { onError: (e) => (got = e) });
    expect(got).toBe("something broke");
  });

  it("ignores malformed frames instead of aborting the stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse(["data: {not json}\n\n", frame("token", "survived"), "data: [DONE]\n\n"])
      )
    );
    const tokens: string[] = [];
    await streamChat("q", undefined, { onToken: (t) => tokens.push(t) });
    expect(tokens).toEqual(["survived"]);
  });

  it("throws ApiError on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([], false, 429)));
    await expect(streamChat("q", undefined, {})).rejects.toBeInstanceOf(ApiError);
  });

  it("sends pinned document_ids, and null when none are pinned", async () => {
    const fetchMock = makeFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    await streamChat("q", undefined, { documentIds: ["d1", "d2"] });
    expect(bodyOf(fetchMock, 0).document_ids).toEqual(["d1", "d2"]);

    await streamChat("q", undefined, {});
    expect(bodyOf(fetchMock, 1).document_ids).toBeNull();
  });

  it("attaches the bearer token", async () => {
    const fetchMock = makeFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    await streamChat("q", undefined, {});
    const headers = initOf(fetchMock, 0).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
  });
});
