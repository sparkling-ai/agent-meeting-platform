"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  roomsApi, messagesApi, agentsApi, moderatorApi, decisionsApi, actionItemsApi,
  type RoomDetail, type Message, type Agent, type ModeratorState,
} from "@/lib/api";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";

const MSG_TYPES = ["chat", "question", "proposal", "objection", "risk", "decision", "action_item", "vote", "summary", "request_ctx"] as const;

const typeStyles: Record<string, string> = {
  chat: "bg-slate-800 border-slate-600",
  question: "bg-blue-950 border-blue-800",
  proposal: "bg-purple-950 border-purple-800",
  objection: "bg-orange-950 border-orange-800",
  risk: "bg-red-950 border-red-800",
  decision: "bg-emerald-950 border-emerald-800",
  action_item: "bg-indigo-950 border-indigo-800",
  vote: "bg-amber-950 border-amber-800",
  summary: "bg-teal-950 border-teal-800",
  request_ctx: "bg-cyan-950 border-cyan-800",
  system: "bg-slate-900 border-slate-700",
};

const typeIcons: Record<string, string> = {
  chat: "💬", question: "❓", proposal: "📋", objection: "⚠️", risk: "🔴",
  decision: "✅", action_item: "📌", vote: "🗳️", summary: "📝", request_ctx: "🔍", system: "⚙️",
};

const typeAccent: Record<string, string> = {
  chat: "text-slate-300", question: "text-blue-300", proposal: "text-purple-300", objection: "text-orange-300",
  risk: "text-red-300", decision: "text-emerald-300", action_item: "text-indigo-300", vote: "text-amber-300",
  summary: "text-teal-300", request_ctx: "text-cyan-300", system: "text-slate-400",
};

export default function RoomView() {
  const params = useParams();
  const roomId = params.id as string;

  const [room, setRoom] = useState<RoomDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [moderatorState, setModeratorState] = useState<ModeratorState | null>(null);
  const [decisions, setDecisions] = useState<Array<{ id: string; content: string }>>([]);
  const [actionItems, setActionItems] = useState<Array<{ id: string; content: string; status: string }>>([]);
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
        messagesApi.list(roomId, { limit: 200 }),
        agentsApi.list(),
      ]);
      setRoom(r);
      setMessages(msgResp.messages);
      setAgents(a);
      if (a.length > 0 && !selectedAgent) setSelectedAgent(a[0].id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [roomId, selectedAgent]);

  // Load moderator state & decisions
  const loadExtras = useCallback(async () => {
    try {
      const [mod, dec, actions] = await Promise.all([
        moderatorApi.getState(roomId).catch(() => null),
        decisionsApi.list(roomId).catch(() => []),
        actionItemsApi.list(roomId).catch(() => []),
      ]);
      setModeratorState(mod);
      setDecisions(dec as any[]);
      setActionItems(actions as any[]);
    } catch {}
  }, [roomId]);

  useEffect(() => { loadRoom(); }, [roomId]);
  useEffect(() => { loadExtras(); }, [roomId]);

  // Poll messages every 2s (fallback when WS not connected)
  useEffect(() => {
    if (connected) return; // WS handles it
    const interval = setInterval(async () => {
      try {
        const resp = await messagesApi.list(roomId, { limit: 200 });
        setMessages(resp.messages);
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [roomId, connected]);

  // Poll moderator state & extras (fallback when WS not connected)
  useEffect(() => {
    if (connected) return;
    const interval = setInterval(loadExtras, 3000);
    return () => clearInterval(interval);
  }, [roomId, connected, loadExtras]);

  // Handle WS events
  useEffect(() => {
    if (!lastEvent) return;
    const { event, data } = lastEvent;

    // New message (live or recent from reconnect)
    if (event === "new_message" || event === "recent_message") {
      const msg = data as unknown as Message;
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        return [...prev, msg];
      });
    }

    // Agent joined / left → refresh room members
    if (event === "agent_joined" || event === "agent_left") {
      roomsApi.get(roomId).then(setRoom).catch(() => {});
    }

    // Room status changed → refresh room
    if (event === "room_status_changed") {
      roomsApi.get(roomId).then(setRoom).catch(() => {});
    }

    // Decision made → refresh decisions list
    if (event === "decision_made" || event === "decision_created") {
      decisionsApi.list(roomId).then(setDecisions).catch(() => {});
    }

    // Moderator action → refresh moderator state
    if (event === "moderator_action") {
      moderatorApi.getState(roomId).then(setModeratorState).catch(() => {});
      // Also refresh decisions & action items since moderator can create them
      loadExtras();
    }

    // Errors from WS
    if (event === "error") {
      const msg = (data as Record<string, unknown>)?.message;
      if (msg && typeof msg === "string") setError(msg);
    }
  }, [lastEvent, roomId, loadExtras]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ensureToken = async (agentId: string) => {
    if (!agentId) return;
    try {
      const resp = await agentsApi.getToken(agentId);
      setAgentToken(resp.token);
    } catch {}
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
      if (!connected) {
        const resp = await messagesApi.list(roomId, { limit: 200 });
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

  const handleActivate = async () => {
    try {
      await roomsApi.activate(roomId);
      loadRoom();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to activate");
    }
  };

  const handleClose = async () => {
    if (!confirm("Close this meeting?")) return;
    try {
      await roomsApi.close(roomId);
      loadRoom();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to close");
    }
  };

  const handleStartModerator = async () => {
    try {
      const state = await moderatorApi.start(roomId);
      setModeratorState(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start moderator");
    }
  };

  const agentNameMap: Record<string, string> = {};
  agents.forEach((a) => { agentNameMap[a.id] = a.name; });
  if (room) {
    room.members.forEach((m) => { if (!agentNameMap[m.agent_id]) agentNameMap[m.agent_id] = m.agent_name; });
  }

  const topLevel = messages.filter((m) => !m.parent_id);
  const replies = messages.filter((m) => m.parent_id);
  const repliesByParent: Record<string, Message[]> = {};
  replies.forEach((r) => {
    if (!repliesByParent[r.parent_id!]) repliesByParent[r.parent_id!] = [];
    repliesByParent[r.parent_id!].push(r);
  });

  if (!room) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>
  );

  return (
    <div className="flex h-[calc(100vh-52px)]">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Room header */}
        <div className="bg-slate-900 border-b border-slate-700 px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <Link href="/" className="text-slate-400 hover:text-white transition shrink-0">←</Link>
              <h1 className="text-xl font-bold text-white truncate">{room.name}</h1>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium shrink-0 ${
                room.status === "active" ? "bg-emerald-900 text-emerald-200" :
                room.status === "archived" ? "bg-amber-900 text-amber-200" :
                "bg-slate-700 text-slate-300"
              }`}>
                {room.status}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${connected ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"}`}>
                {connected ? "● Live" : "○ Polling"}
              </span>
            </div>
            <div className="flex gap-2 shrink-0 ml-4">
              {room.status === "draft" && (
                <button onClick={handleActivate} className="bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-emerald-700 transition font-medium">
                  ▶ Activate
                </button>
              )}
              {room.status === "active" && (
                <>
                  <button onClick={handleStartModerator} className="bg-purple-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-purple-700 transition font-medium">
                    🎯 Start Moderator
                  </button>
                  <button onClick={handleClose} className="bg-red-700 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-red-800 transition font-medium">
                    Close Meeting
                  </button>
                </>
              )}
            </div>
          </div>
          {room.topic && <p className="text-sm text-slate-400 mt-1 truncate">{room.topic}</p>}
        </div>

        {/* Moderator Phase Bar */}
        {moderatorState && moderatorState.status === "running" && (
          <div className="bg-purple-900/40 border-b border-purple-700 px-6 py-2">
            <div className="flex items-center gap-4">
              <span className="text-purple-300 text-sm font-medium">🎯 Moderator Active</span>
              {moderatorState.current_phase && (
                <span className="text-purple-200 text-sm">Phase: {moderatorState.current_phase}</span>
              )}
              {moderatorState.current_item && (
                <span className="text-purple-200/70 text-sm">— {moderatorState.current_item}</span>
              )}
              <div className="flex gap-1 ml-auto">
                {moderatorState.phases?.map((p, i) => (
                  <div
                    key={i}
                    className={`h-2 w-8 rounded-full ${
                      p.status === "completed" ? "bg-emerald-500" :
                      p.status === "active" ? "bg-purple-400 animate-pulse" :
                      "bg-slate-600"
                    }`}
                    title={p.name}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {topLevel.length === 0 && (
            <div className="text-center py-16">
              <p className="text-slate-500 text-lg">No messages yet</p>
              <p className="text-slate-600 text-sm mt-1">Start the conversation!</p>
            </div>
          )}
          {topLevel.map((msg) => (
            <div key={msg.id} className={`rounded-xl border p-4 ${typeStyles[msg.type] || typeStyles.chat}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm">{typeIcons[msg.type] || "💬"}</span>
                <span className="font-medium text-sm text-white">{agentNameMap[msg.agent_id || ""] || "System"}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full bg-black/30 ${typeAccent[msg.type] || "text-slate-400"}`}>
                  {msg.type}
                </span>
                <span className="text-xs text-slate-500 ml-auto">{new Date(msg.created_at).toLocaleTimeString()}</span>
              </div>
              <p className="text-sm whitespace-pre-wrap text-slate-200">{msg.content}</p>
              <button
                onClick={() => setReplyTo(msg.id)}
                className="text-xs text-slate-500 hover:text-slate-300 mt-2 transition"
              >
                ↩ Reply
              </button>
              {repliesByParent[msg.id]?.length > 0 && (
                <div className="ml-4 mt-3 space-y-2 border-l-2 border-slate-600 pl-3">
                  {repliesByParent[msg.id].map((r) => (
                    <div key={r.id} className={`rounded-lg border p-3 ${typeStyles[r.type] || typeStyles.chat}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs">{typeIcons[r.type]}</span>
                        <span className="font-medium text-xs text-white">{agentNameMap[r.agent_id || ""] || "Unknown"}</span>
                        <span className="text-xs text-slate-500">{new Date(r.created_at).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-xs whitespace-pre-wrap text-slate-300">{r.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Composer */}
        <div className="bg-slate-900 border-t border-slate-700 p-4">
          {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-2 rounded-lg text-sm mb-2">{error}</div>}
          {replyTo && (
            <div className="flex items-center gap-2 mb-2 text-sm text-slate-400">
              ↩ Replying to: {messages.find((m) => m.id === replyTo)?.content.slice(0, 50)}...
              <button onClick={() => setReplyTo(null)} className="text-red-400 hover:text-red-300">✕</button>
            </div>
          )}
          <div className="flex gap-2">
            <select
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
            >
              <option value="">Agent</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <select
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              value={msgType}
              onChange={(e) => setMsgType(e.target.value)}
            >
              {MSG_TYPES.map((t) => (
                <option key={t} value={t}>{typeIcons[t]} {t}</option>
              ))}
            </select>
            <input
              className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none"
              placeholder="Type a message..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            />
            <button
              onClick={handleSend}
              disabled={!content.trim() || !selectedAgent}
              className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition font-medium"
            >
              Send
            </button>
          </div>
        </div>
      </div>

      {/* Sidebar */}
      <div className="w-72 bg-slate-900 border-l border-slate-700 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-4">
          {/* Members */}
          <h2 className="font-semibold text-sm text-slate-400 uppercase tracking-wider mb-3">
            Members ({room.members.length})
          </h2>
          {room.members.length === 0 && <p className="text-slate-600 text-sm mb-4">No members yet</p>}
          <div className="space-y-1 mb-4">
            {room.members.map((m) => (
              <div key={m.agent_id} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-800">
                <span className="text-sm text-slate-300">🤖 {m.agent_name}</span>
                <div className="flex items-center gap-1.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    m.role === "owner" ? "bg-yellow-900 text-yellow-300" :
                    m.role === "moderator" ? "bg-purple-900 text-purple-300" :
                    m.role === "observer" ? "bg-slate-700 text-slate-400" :
                    "bg-blue-900 text-blue-300"
                  }`}>
                    {m.role}
                  </span>
                  {m.role !== "owner" && (
                    <>
                      <select
                        className="bg-slate-800 border border-slate-600 rounded text-xs px-1 py-0.5 text-white"
                        value={m.role}
                        onChange={(e) => {
                          if (e.target.value !== m.role) {
                            roomsApi.updateRole(roomId, m.agent_id, e.target.value)
                              .then(() => loadRoom())
                              .catch((e) => setError(e.message));
                          }
                        }}
                      >
                        <option value="moderator">moderator</option>
                        <option value="member">member</option>
                        <option value="observer">observer</option>
                      </select>
                      <button
                        className="text-red-400 hover:text-red-300 text-xs"
                        onClick={() => {
                          if (confirm(`Kick ${m.agent_name}?`)) {
                            roomsApi.kick(roomId, m.agent_id)
                              .then(() => loadRoom())
                              .catch((e) => setError(e.message));
                          }
                        }}
                        title="Kick member"
                      >✕</button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          <hr className="border-slate-700 my-4" />

          {/* Join Room */}
          {agents.filter((a) => !room.members.some((m) => m.agent_id === a.id)).length > 0 && (
            <>
              <h2 className="font-semibold text-sm text-slate-400 uppercase tracking-wider mb-3">Join Room</h2>
              <div className="space-y-2 mb-4">
                {agents.filter((a) => !room.members.some((m) => m.agent_id === a.id)).map((a) => (
                  <div key={a.id} className="flex items-center justify-between px-2">
                    <span className="text-sm text-slate-400">{a.name}</span>
                    <select
                      className="bg-slate-800 border border-slate-600 rounded text-xs px-2 py-1 text-white"
                      defaultValue=""
                      onChange={(e) => { if (e.target.value) handleJoin(a.id, e.target.value); }}
                    >
                      <option value="">Join as...</option>
                      <option value="member">Member</option>
                      <option value="moderator">Moderator</option>
                      <option value="observer">Observer</option>
                    </select>
                  </div>
                ))}
              </div>
              <hr className="border-slate-700 my-4" />
            </>
          )}

          {/* Decisions */}
          <h2 className="font-semibold text-sm text-emerald-400 uppercase tracking-wider mb-3">
            ✅ Decisions ({decisions.length})
          </h2>
          {decisions.length === 0 && messages.filter(m => m.type === "decision").length === 0 ? (
            <p className="text-slate-600 text-sm mb-4">No decisions yet</p>
          ) : (
            <div className="space-y-2 mb-4">
              {(decisions.length > 0 ? decisions : messages.filter(m => m.type === "decision").map(m => ({id: m.id, content: m.content}))).map((d) => (
                <div key={d.id} className="bg-emerald-950 border border-emerald-800 rounded-lg p-2.5 text-sm text-emerald-200">
                  ✅ {d.content.slice(0, 100)}
                </div>
              ))}
            </div>
          )}

          <hr className="border-slate-700 my-4" />

          {/* Action Items */}
          <h2 className="font-semibold text-sm text-indigo-400 uppercase tracking-wider mb-3">
            📌 Action Items ({actionItems.length})
          </h2>
          {actionItems.length === 0 && messages.filter(m => m.type === "action_item").length === 0 ? (
            <p className="text-slate-600 text-sm">No action items yet</p>
          ) : (
            <div className="space-y-2">
              {(actionItems.length > 0 ? actionItems : messages.filter(m => m.type === "action_item").map(m => ({id: m.id, content: m.content, status: "open"}))).map((a) => (
                <div key={a.id} className="bg-indigo-950 border border-indigo-800 rounded-lg p-2.5 text-sm text-indigo-200">
                  📌 {a.content.slice(0, 100)}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
