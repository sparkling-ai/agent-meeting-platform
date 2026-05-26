"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { roomsApi, agentsApi, type Room, type Agent } from "@/lib/api";

const statusColors: Record<string, string> = {
  draft: "bg-gray-200 text-gray-700",
  active: "bg-green-100 text-green-800",
  archived: "bg-yellow-100 text-yellow-800",
};

export default function Home() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [error, setError] = useState("");

  const loadData = async () => {
    try {
      const [r, a] = await Promise.all([roomsApi.list(), agentsApi.list()]);
      setRooms(r);
      setAgents(a);
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
      await roomsApi.create({ name: name.trim(), topic: topic.trim() || undefined });
      setName("");
      setTopic("");
      setShowCreate(false);
      loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  };

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Meeting Rooms</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
        >
          + Create Room
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {showCreate && (
        <div className="bg-white p-6 rounded-lg shadow mb-6 border">
          <h2 className="text-lg font-semibold mb-3">Create New Room</h2>
          <input
            className="w-full border rounded px-3 py-2 mb-3"
            placeholder="Room name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="w-full border rounded px-3 py-2 mb-3"
            placeholder="Topic (optional)"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <div className="flex gap-2">
            <button onClick={createRoom} className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="bg-gray-200 px-4 py-2 rounded hover:bg-gray-300">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {rooms.length === 0 && (
          <p className="text-gray-500 text-center py-8">No rooms yet. Create one to get started!</p>
        )}
        {rooms.map((room) => (
          <Link
            key={room.id}
            href={`/rooms/${room.id}`}
            className="block bg-white p-4 rounded-lg shadow hover:shadow-md transition border"
          >
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-lg">{room.name}</h3>
                {room.topic && <p className="text-gray-500 text-sm">{room.topic}</p>}
              </div>
              <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[room.status] || "bg-gray-100"}`}>
                {room.status}
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-2">
              Created {new Date(room.created_at).toLocaleString()}
            </p>
          </Link>
        ))}
      </div>

      <div className="mt-8 bg-white p-4 rounded-lg shadow border">
        <h2 className="font-semibold mb-2">Registered Agents ({agents.length})</h2>
        {agents.length === 0 ? (
          <p className="text-gray-500 text-sm">
            No agents yet. <Link href="/admin/agents" className="text-blue-600 underline">Create some</Link> first.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {agents.map((a) => (
              <span key={a.id} className="bg-gray-100 px-3 py-1 rounded-full text-sm">{a.name}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
