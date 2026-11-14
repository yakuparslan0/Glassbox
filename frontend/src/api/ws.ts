import type { RunEvent } from "../types/generated";

export interface RunConnection {
  cancel: () => void;
  close: () => void;
}

/**
 * Stream a run's events. Batches are queued and handed to `onEvents` once per animation frame (never per event).
 * A dropped socket reconnects with `?from_seq=` so no event is lost or duplicated.
 */
export function connectRun(
  runId: string,
  onEvents: (events: RunEvent[]) => void,
  onFinished: () => void,
  onFailed: () => void,
): RunConnection {
  let socket: WebSocket | null = null;
  let lastSeq = 0;
  let done = false;
  let retries = 0;
  let queue: RunEvent[] = [];
  let scheduled = false;

  const flush = (): void => {
    scheduled = false;
    if (!queue.length) return;
    const batch = queue;
    queue = [];
    onEvents(batch);
  };

  const open = (): void => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws/runs/${runId}?from_seq=${lastSeq}`);
    socket.onmessage = (msg: MessageEvent<string>) => {
      retries = 0;
      const { batch } = JSON.parse(msg.data) as { batch: RunEvent[] };
      for (const ev of batch) {
        if (ev.seq <= lastSeq) continue;
        lastSeq = ev.seq;
        queue.push(ev);
        if (ev.type === "run_finished") done = true;
      }
      if (!scheduled) {
        scheduled = true;
        requestAnimationFrame(flush);
      }
    };
    socket.onclose = () => {
      if (done) {
        flush();
        onFinished();
      } else if (retries < 5) {
        retries++;
        setTimeout(open, 300 * retries);
      } else onFailed();
    };
  };
  open();

  return {
    cancel: () => socket?.readyState === WebSocket.OPEN && socket.send(JSON.stringify({ cmd: "cancel" })),
    close: () => {
      done = true;
      socket?.close();
    },
  };
}
