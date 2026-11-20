import { useEffect, useRef, useState } from "react";

import { groups, useInvalidate } from "@/api/queries";
import { sessionStore } from "@/api/session";

export type LiveState = "connecting" | "live" | "offline";

/**
 * NFR-2: server pushes signals ("queue changed"); we refetch over REST. Reconnects with backoff and
 * re-authenticates whenever the access token rotates. Signals never carry patient data.
 */
export function useLiveEvents(enabled: boolean): LiveState {
  const invalidate = useInvalidate();
  const invalidateRef = useRef(invalidate);
  invalidateRef.current = invalidate;
  const [state, setState] = useState<LiveState>("connecting");
  const [token, setToken] = useState(sessionStore.get()?.accessToken);

  useEffect(() => sessionStore.subscribe((s) => setToken(s?.accessToken)), []);

  useEffect(() => {
    if (!enabled || !token) return;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setState("connecting");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
      ws.onopen = () => ws?.send(JSON.stringify({ type: "auth", token }));
      ws.onmessage = (ev) => {
        let msg: { type?: string };
        try {
          msg = JSON.parse(String(ev.data)) as { type?: string };
        } catch {
          return;
        }
        if (msg.type === "ready") {
          attempt = 0;
          setState("live");
          void invalidateRef.current([...groups.schedule, ...groups.inbox]); // catch up after reconnect
        } else if (msg.type?.startsWith("queue")) {
          void invalidateRef.current(groups.queue);
        } else if (msg.type?.startsWith("inbox")) {
          void invalidateRef.current(groups.inbox);
        } else if (msg.type?.startsWith("calls")) {
          void invalidateRef.current(["missed-calls", "today"]);
        }
      };
      ws.onclose = () => {
        setState("offline");
        if (stopped) return;
        const delay = Math.min(30_000, 1000 * 2 ** attempt++);
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [enabled, token]);

  return state;
}
