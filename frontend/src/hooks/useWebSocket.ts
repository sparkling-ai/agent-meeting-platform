"use client";

import { useEffect, useRef, useCallback, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface WsMessage {
  event: string;
  data: Record<string, unknown>;
}

export function useWebSocket(roomId: string | null, agentToken: string | null) {
  const [lastEvent, setLastEvent] = useState<WsMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!roomId || !agentToken) return;

    const ws = new WebSocket(`${API_BASE.replace(/^http/, "ws")}/api/rooms/${roomId}/ws?token=${agentToken}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      // Reconnect after 2s
      reconnectRef.current = setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        setLastEvent(msg);
      } catch { /* ignore bad json */ }
    };

    wsRef.current = ws;
  }, [roomId, agentToken]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((data: { type: string; content: string; parent_id?: string }) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { lastEvent, connected, send };
}
