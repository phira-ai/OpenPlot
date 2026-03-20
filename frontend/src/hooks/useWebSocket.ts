import { useEffect, useRef, useCallback, useMemo, useState } from "react";
import type { WsEvent } from "../types";

/**
 * Connect to the OpenPlot WebSocket and dispatch incoming events.
 */
export function useWebSocket(onEvent: (event: WsEvent) => void) {
  const [connected, setConnected] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [lastConnectedAt, setLastConnectedAt] = useState<string | null>(null);
  const [lastDisconnectedAt, setLastDisconnectedAt] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const onEventRef = useRef(onEvent);
  const wsUrl = useMemo(() => {
    if (typeof window === "undefined") {
      return "";
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws`;
  }, []);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let disposed = false;

    function clearReconnectTimer() {
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    }

    function clearHeartbeatTimer() {
      if (heartbeatTimer !== null) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    }

    function scheduleReconnect() {
      if (disposed) {
        return;
      }
      clearReconnectTimer();
      setConnected(false);
      setReconnectAttempts((n) => n + 1);
      setLastDisconnectedAt(new Date().toISOString());
      reconnectTimer = setTimeout(connect, 2000);
    }

    function connect() {
      if (!wsUrl) {
        scheduleReconnect();
        return;
      }

      let socket: WebSocket;
      try {
        socket = new WebSocket(wsUrl);
      } catch {
        scheduleReconnect();
        return;
      }

      ws = socket;
      wsRef.current = socket;

      socket.addEventListener("open", () => {
        clearReconnectTimer();
        clearHeartbeatTimer();

        setConnected(true);
        setReconnectAttempts(0);
        setLastConnectedAt(new Date().toISOString());

        heartbeatTimer = setInterval(() => {
          if (!ws || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          ws.send("ping");
        }, 15000);
      });

      socket.addEventListener("message", (ev) => {
        try {
          const event: WsEvent = JSON.parse(ev.data);
          onEventRef.current(event);
        } catch {
          // Ignore non-JSON messages.
        }
      });

      socket.addEventListener("close", () => {
        clearHeartbeatTimer();
        scheduleReconnect();
      });

      socket.addEventListener("error", () => {
        socket.close();
      });
    }

    connect();

    return () => {
      disposed = true;
      clearReconnectTimer();
      clearHeartbeatTimer();
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [wsUrl]);

  const send = useCallback((data: string) => {
    wsRef.current?.send(data);
  }, []);

  return {
    connected,
    send,
    wsUrl,
    reconnectAttempts,
    lastConnectedAt,
    lastDisconnectedAt,
  };
}
