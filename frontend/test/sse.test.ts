import { describe, expect, it } from "vitest";
import { SseParser } from "../src/lib/sseParser";

describe("SseParser", () => {
  it("assembles messages split across arbitrary chunk boundaries", () => {
    const p = new SseParser();
    const wire = 'event: meta\ndata: {"a":1}\n\nevent: token\ndata: {"text":"Hel\\nlo"}\n\nevent: done\ndata: {}\n\n';
    const got = [];
    for (let i = 0; i < wire.length; i += 7) got.push(...p.push(wire.slice(i, i + 7)));
    expect(got).toEqual([
      { event: "meta", data: { a: 1 } },
      { event: "token", data: { text: "Hel\nlo" } },
      { event: "done", data: {} },
    ]);
  });

  it("handles CRLF and skips malformed or empty blocks without breaking the stream", () => {
    const p = new SseParser();
    const got = p.push('event: x\r\ndata: not-json\r\n\r\n: comment\n\nevent: ok\ndata: {"v":2}\n\n');
    expect(got).toEqual([{ event: "ok", data: { v: 2 } }]);
  });
});
