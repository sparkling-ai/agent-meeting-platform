"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { roomsApi, agentsApi, type Room, type Agent } from "@/lib/api";

const statusColors: Record<string, string> = {
  draft: "bg-slate-600 text-slate-200",
  active: "bg-emerald-900 text-emerald-200 border-emerald-700",
  archived: "bg-amber-900 text-amber-200 border-amber-700",
};

const statusDot: Record<string, string> = {
  draft: "bg-slate-400",
  active: "bg-emerald-400 animate-pulse",
  archived: "bg-amber-400",
};

export default function Home() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [agenda, setAgenda] = useState("");
  const [error, setError] = useState("");

  const loadData = async () => {
    try {
      const [r, a] = await Promise.all([roomsApi.list(), agentsApi.list()]);
      setRooms(r);
      setAgents(a);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const createRoom = async () => {
    if (!name.trim()) return;
    try {
      await roomsApi.create({ name: name.trim(), topic: topic.trim() || undefined, agenda: agenda.trim() || undefined });
      setName("");
      setTopic("");
      setAgenda("");
      setShowCreate(false);
      loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>
  );

  const activeRooms = rooms.filter(r => r.status === "active");
  const draftRooms = rooms.filter(r => r.status === "draft");
  const archivedRooms = rooms.filter(r => r.status === "archived");

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white">Meeting Rooms</h1>
          <p className="text-slate-400 mt-1">{rooms.length} rooms · {activeRooms.length} active</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700 transition font-medium"
        >
          + Create Room
        </button>
      </div>

      {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">{error}</div>}

      {showCreate && (
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 mb-6">
          <h2 className="text-lg font-semibold mb-4 text-white">Create New Room</h2>
          <input
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-3 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none"
            placeholder="Room name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <textarea
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-3 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none resize-none"
            placeholder="Topic description"
            rows={2}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <textarea
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-4 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none resize-none"
            placeholder="Agenda items (one per line)"
            rows={3}
            value={agenda}
            onChange={(e) => setAgenda(e.target.value)}
          />
          <div className="flex gap-2">
            <button onClick={createRoom} className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 transition">
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="bg-slate-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-slate-600 transition">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Active Rooms */}
      {activeRooms.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-emerald-400 uppercase tracking-wider mb-3">🟢 Active Meetings</h2>
          <div className="grid gap-3">
            {activeRooms.map((room) => (
              <Link
                key={room.id}
                href={`/rooms/${room.id}`}
                className="block bg-slate-800/80 p-4 rounded-xl border border-slate-700 hover:border-emerald-600 hover:bg-slate-800 transition group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${statusDot[room.status]}`} />
                      <h3 className="font-semibold text-white group-hover:text-emerald-300 truncate">{room.name}</h3>
                    </div>
                    {room.topic && <p className="text-slate-400 text-sm mt-1 truncate">{room.topic}</p>}
                  </div>
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ml-3 ${statusColors[room.status]}`}>
                    {room.status}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  {new Date(room.created_at).toLocaleString()}
                </p>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Draft Rooms */}
      {draftRooms.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">📝 Draft Rooms</h2>
          <div className="grid gap-3">
            {draftRooms.map((room) => (
              <Link
                key={room.id}
                href={`/rooms/${room.id}`}
                className="block bg-slate-800/50 p-4 rounded-xl border border-slate-700 hover:border-slate-500 hover:bg-slate-800 transition group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-slate-200 group-hover:text-white truncate">{room.name}</h3>
                    {room.topic && <p className="text-slate-400 text-sm mt-1 truncate">{room.topic}</p>}
                  </div>
                  <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 ml-3">
                    draft
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Archived Rooms */}
      {archivedRooms.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-amber-400/70 uppercase tracking-wider mb-3">📁 Archived ({archivedRooms.length})</h2>
          <div className="grid gap-2">
            {archivedRooms.slice(0, 5).map((room) => (
              <Link
                key={room.id}
                href={`/rooms/${room.id}`}
                className="block bg-slate-800/30 p-3 rounded-lg border border-slate-700/50 hover:border-slate-600 transition group"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm text-slate-400 group-hover:text-slate-200 truncate">{room.name}</h3>
                  <span className="text-xs text-slate-500">{new Date(room.created_at).toLocaleDateString()}</span>
                </div>
              </Link>
            ))}
            {archivedRooms.length > 5 && (
              <p className="text-xs text-slate-500 text-center py-2">...and {archivedRooms.length - 5} more</p>
            )}
          </div>
        </div>
      )}

      {rooms.length === 0 && (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg mb-2">No rooms yet</p>
          <p className="text-slate-500">Create one to get started!</p>
        </div>
      )}

      {/* Agents Bar */}
      <div className="mt-8 bg-slate-800/50 p-4 rounded-xl border border-slate-700">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-slate-300">Registered Agents</h2>
          <Link href="/admin/agents" className="text-sm text-blue-400 hover:text-blue-300">Manage →</Link>
        </div>
        {agents.length === 0 ? (
          <p className="text-slate-500 text-sm">No agents yet. <Link href="/admin/agents" className="text-blue-400 underline">Create some</Link> first.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {agents.map((a) => (
              <span key={a.id} className="bg-slate-700 px-3 py-1.5 rounded-full text-sm text-slate-300 border border-slate-600">
                🤖 {a.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
