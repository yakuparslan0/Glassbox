// Incremental Server-Sent-Events parser (we use fetch + a reader so we control closing and errors).
export interface SseMessage {
  event: string;
  data: unknown;
}

export class SseParser {
  private buffer = "";

  /** Feed a text chunk; returns the complete messages it finished. */
  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const out: SseMessage[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) >= 0) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (!data.length) continue;
      try {
        out.push({ event, data: JSON.parse(data.join("\n")) });
      } catch {
        /* a malformed block is skipped rather than breaking the stream */
      }
    }
    return out;
  }
}

export async function readSse(url: string, onMessage: (m: SseMessage) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(url, { signal, headers: { Accept: "text/event-stream" } });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    for (const m of parser.push(value)) onMessage(m);
  }
}
