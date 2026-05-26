"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  roomsApi, messagesApi, agentsApi,
  type RoomDetail, type Message, type Agent,
} from "@/lib/api";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";

const MSG_TYPES = ["chat", "question", "proposal", "objection", "risk", "decision", "action_item", "vote", "summary", "request_ctx"] as const;

const typeStyles: Record<string, string> = {
  chat: "bg-gray-50 border-gray-200",
  question: "bg-blue-50 border-blue-300",
  proposal: "bg-purple-50 border-purple-300",
  objection: "bg-orange-50 border-orange-300",
  risk: "bg-red-50 border-red-300",
  decision: "bg-green-50 border-green-300",
  action_item: "bg-indigo-50 border-indigo-300",
  vote: "bg-yellow-50 border-yellow-300",
  summary: "bg-teal-50 border-teal-300",
  request_ctx: "bg-cyan-50 border-cyan-300",
};

const typeIcons: Record<string, string> = {
  chat: "💬", question: "❓", proposal: "📋", objection: "⚠️", risk: "🔴",
  decision: "✅", action_item: "📌", vote: "🗳️", summary: "📝", request_ctx: "🔍",
};

export default function RoomView() {
  const params = useParams();
  const roomId = params.id as string;

  const [room, setRoom] = useState<RoomDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState("");

  // Composer state
  const [content, setContent] = useState("");
  const [msgType, setMsgType] = useState<string>("chat");
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [agentToken, setAgentToken] = useState<string>("");
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // WS
  const { lastEvent, connected, send } = useWebSocket(roomId, agentToken || null);

  const loadRoom = useCallback(async () => {
    try {
      const [r, msgResp, a] = await Promise.all([
        roomsApi.get(roomId),
        messagesApi.list(roomId, { limit: 100 }),
        agentsApi.list(),
      ]);
      setRoom(r);
      setMessages(msgResp.messages);
      setAgents(a);
      if (a.length > 0 && !selectedAgent) setSelectedAgent(a[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [roomId, selectedAgent]);

  useEffect(() => { loadRoom(); }, [roomId]);

  // Handle WS events
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.event === "new_message" && lastEvent.data) {
      const msg = lastEvent.data as unknown as Message;
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        return [...prev, msg];
      });
    }
    if (lastEvent.event === "agent_joined" || lastEvent.event === "agent_left") {
      roomsApi.get(roomId).then(setRoom);
    }
  }, [lastEvent, roomId]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Get token for selected agent
  const ensureToken = async (agentId: string) => {
    if (!agentId) return;
    try {
      const resp = await agentsApi.getToken(agentId);
      setAgentToken(resp.token);
    } catch {
      // token might already exist
    }
  };

  useEffect(() => {
    if (selectedAgent) ensureToken(selectedAgent);
  }, [selectedAgent]);

  const handleSend = async () => {
    if (!content.trim() || !selectedAgent) return;
    try {
      if (connected) {
        send({ type: msgType, content: content.trim(), parent_id: replyTo || undefined });
      } else {
        await messagesApi.send(roomId, {
          agent_id: selectedAgent,
          type: msgType,
          content: content.trim(),
          parent_id: replyTo || undefined,
        });
      }
      setContent("");
      setReplyTo(null);
      // Refresh if not WS
      if (!connected) {
        const resp = await messagesApi.list(roomId, { limit: 100 });
        setMessages(resp.messages);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send");
    }
  };

  const handleJoin = async (agentId: string, role: string) => {
    try {
      await roomsApi.join(roomId, { agent_id: agentId, role });
      loadRoom();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to join");
    }
  };

  const handleStatusChange = async (status: string) => {
    try {
      await roomsApi.updateStatus(roomId, status);
      loadRoom();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    }
  };

  const agentNameMap = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  // Also include members from room
  if (room) {
    room.members.forEach((m) => { if (!agentNameMap[m.agent_id]) agentNameMap[m.agent_id] = m.agent_name; });
  }

  // Build threads
  const topLevel = messages.filter((m) => !m.parent_id);
  const replies = messages.filter((m) => m.parent_id);
  const repliesByParent: Record<string, Message[]> = {};
  replies.forEach((r) => {
    if (!repliesByParent[r.parent_id!]) repliesByParent[r.parent_id!] = [];
    repliesByParent[r.parent_id!].push(r);
  });

  if (!room) return <div className="p-8 text-center text-gray-500">Loading room...</div>;

  return (
    <div className="flex h-[calc(100vh-52px)]">
      {/* Main content */}
      <div className="flex-1 flex flex-col">
        {/* Room header */}
        <div className="bg-white border-b px-6 py-3 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <Link href="/" className="text-gray-400 hover:text-gray-600">← Back</Link>
              <h1 className="text-xl font-bold">{room.name}</h1>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                room.status === "active" ? "bg-green-100 text-green-800" :
                room.status === "archived" ? "bg-yellow-100 text-yellow-800" :
                "bg-gray-100 text-gray-700"
              }`}>
                {room.status}
              </span>
            </div>
            {room.topic && <p className="text-sm text-gray-500 mt-1">{room.topic}</p>}
          </div>
          <div className="flex gap-2">
            {room.status === "draft" && (
              <button onClick={() => handleStatusChange("active")} className="bg-green-600 text-white px-3 py-1 rounded text-sm hover:bg-green-700">
                Activate
              </button>
            )}
            {room.status === "active" && (
              <button onClick={() => handleStatusChange("archived")} className="bg-yellow-600 text-white px-3 py-1 rounded text-sm hover:bg-yellow-700">
                Archive
              </button>
            )}
            <span className={`text-xs px-2 py-1 rounded ${connected ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
              {connected ? "WS Connected" : "WS Disconnected"}
            </span>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {topLevel.length === 0 && (
            <p className="text-center text-gray-400 py-12">No messages yet. Start the conversation!</p>
          )}
          {topLevel.map((msg) => (
            <div key={msg.id} className={`rounded-lg border p-3 ${typeStyles[msg.type] || "bg-gray-50"}`}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm">{typeIcons[msg.type] || "💬"}</span>
                <span className="font-medium text-sm">{agentNameMap[msg.agent_id || ""] || "Unknown"}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-white/60">{msg.type}</span>
                <span className="text-xs text-gray-400">{new Date(msg.created_at).toLocaleTimeString()}</span>
              </div>
              <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
              <button
                onClick={() => setReplyTo(msg.id)}
                className="text-xs text-gray-400 hover:text-gray-600 mt-1"
              >
                ↩ Reply
              </button>
              {repliesByParent[msg.id]?.length > 0 && (
                <div className="ml-4 mt-2 space-y-2 border-l-2 pl-3">
                  {repliesByParent[msg.id].map((r) => (
                    <div key={r.id} className={`rounded border p-2 ${typeStyles[r.type] || "bg-gray-50"}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm">{typeIcons[r.type]}</span>
                        <span className="font-medium text-xs">{agentNameMap[r.agent_id || ""] || "Unknown"}</span>
                        <span className="text-xs text-gray-400">{new Date(r.created_at).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-xs whitespace-pre-wrap">{r.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Composer */}
        <div className="bg-white border-t p-4">
          {error && <div className="bg-red-50 text-red-700 p-2 rounded text-sm mb-2">{error}</div>}
          {replyTo && (
            <div className="flex items-center gap-2 mb-2 text-sm text-gray-500">
              Replying to: {messages.find((m) => m.id === replyTo)?.content.slice(0, 50)}...
              <button onClick={() => setReplyTo(null)} className="text-red-400 hover:text-red-600">✕</button>
            </div>
          )}
          <div className="flex gap-2">
            <select
              className="border rounded px-2 py-2 text-sm"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
            >
              <option value="">Select Agent</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <select
              className="border rounded px-2 py-2 text-sm"
              value={msgType}
              onChange={(e) => setMsgType(e.target.value)}
            >
              {MSG_TYPES.map((t) => (
                <option key={t} value={t}>{typeIcons[t]} {t}</option>
              ))}
            </select>
            <input
              className="flex-1 border rounded px-3 py-2 text-sm"
              placeholder="Type a message..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            />
            <button
              onClick={handleSend}
              disabled={!content.trim() || !selectedAgent}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      </div>

      {/* Sidebar */}
      <div className="w-64 bg-white border-l p-4 overflow-y-auto">
        <h2 className="font-semibold mb-3">Members ({room.members.length})</h2>
        {room.members.length === 0 && <p className="text-gray-400 text-sm">No members yet</p>}
        {room.members.map((m) => (
          <div key={m.agent_id} className="flex items-center justify-between py-1.5">
            <div>
              <span className="text-sm">{m.agent_name}</span>
              <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
                m.role === "moderator" ? "bg-purple-100 text-purple-700" :
                m.role === "observer" ? "bg-gray-100 text-gray-600" :
                "bg-blue-100 text-blue-700"
              }`}>
                {m.role}
              </span>
            </div>
          </div>
        ))}

        <hr className="my-4" />

        <h2 className="font-semibold mb-3">Join Room</h2>
        {agents.filter((a) => !room.members.some((m) => m.agent_id === a.id)).length === 0 ? (
          <p className="text-gray-400 text-sm">All agents joined</p>
        ) : (
          <div className="space-y-2">
            {agents.filter((a) => !room.members.some((m) => m.agent_id === a.id)).map((a) => (
              <div key={a.id} className="flex items-center justify-between">
                <span className="text-sm">{a.name}</span>
                <select
                  className="border rounded text-xs px-1 py-0.5"
                  defaultValue="participant"
                  onChange={(e) => handleJoin(a.id, e.target.value)}
                >
                  <option value="participant">Join</option>
                  <option value="moderator">Mod</option>
                  <option value="observer">Observe</option>
                </select>
              </div>
            ))}
          </div>
        )}

        <hr className="my-4" />

        <h2 className="font-semibold mb-3">Decisions</h2>
        {messages.filter((m) => m.type === "decision").length === 0 ? (
          <p className="text-gray-400 text-sm">No decisions yet</p>
        ) : (
          <div className="space-y-2">
            {messages.filter((m) => m.type === "decision").map((m) => (
              <div key={m.id} className="bg-green-50 border border-green-200 rounded p-2 text-sm">
                ✅ {m.content.slice(0, 80)}
              </div>
            ))}
          </div>
        )}

        <hr className="my-4" />

        <h2 className="font-semibold mb-3">Action Items</h2>
        {messages.filter((m) => m.type === "action_item").length === 0 ? (
          <p className="text-gray-400 text-sm">No action items yet</p>
        ) : (
          <div className="space-y-2">
            {messages.filter((m) => m.type === "action_item").map((m) => (
              <div key={m.id} className="bg-indigo-50 border border-indigo-200 rounded p-2 text-sm">
                📌 {m.content.slice(0, 80)}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
