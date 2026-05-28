"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi, roomsApi, type Room } from "@/lib/api";

const statusColors: Record<string, string> = {
  draft: "bg-slate-700 text-slate-300",
  active: "bg-emerald-900 text-emerald-200",
  archived: "bg-amber-900 text-amber-200",
};

const visibilityColors: Record<string, string> = {
  public: "bg-green-900 text-green-200",
  unlisted: "bg-slate-700 text-slate-300",
  private: "bg-red-900 text-red-200",
};

interface AdminRoom {
  id: string;
  name: string;
  topic: string | null;
  status: string;
  visibility: string;
  owner_id: string | null;
  max_participants: number;
  member_count: number;
  created_at: string;
}

export default function RoomsAdmin() {
  const [rooms, setRooms] = useState<AdminRoom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadRooms = async () => {
    try {
      setRooms(await adminApi.listRooms());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadRooms(); }, []);

  const changeStatus = async (id: string, status: string) => {
    try {
      await roomsApi.updateStatus(id, status);
      loadRooms();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    }
  };

  const deleteRoom = async (id: string, name: string) => {
    if (!confirm(`Delete room "${name}"? This cannot be undone.`)) return;
    try {
      await adminApi.deleteRoom(id);
      loadRooms();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <Link href="/" className="text-slate-400 hover:text-white transition">←</Link>
            <h1 className="text-2xl font-bold text-white">Room Administration</h1>
          </div>
          <p className="text-slate-400 mt-1">{rooms.length} rooms</p>
        </div>
        <span className="text-xs bg-red-900 text-red-200 px-3 py-1 rounded-full">Admin</span>
      </div>

      {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">{error}</div>}

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Name</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Visibility</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Status</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Members</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Created</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-slate-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {rooms.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-slate-500">No rooms yet</td></tr>
            ) : (
              rooms.map((room) => (
                <tr key={room.id} className="hover:bg-slate-700/50 transition">
                  <td className="px-4 py-3">
                    <Link href={`/rooms/${room.id}`} className="text-blue-400 hover:text-blue-300 font-medium">
                      {room.name}
                    </Link>
                    {room.topic && <p className="text-slate-500 text-xs mt-0.5 truncate max-w-xs">{room.topic}</p>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${visibilityColors[room.visibility] || "bg-slate-700 text-slate-300"}`}>
                      {room.visibility}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusColors[room.status]}`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-400">
                    {room.member_count}/{room.max_participants}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {new Date(room.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex gap-1 justify-end">
                      {room.status !== "active" && (
                        <button onClick={() => changeStatus(room.id, "active")} className="text-xs bg-emerald-900 text-emerald-200 px-2.5 py-1 rounded hover:bg-emerald-800 transition">
                          Activate
                        </button>
                      )}
                      {room.status !== "archived" && (
                        <button onClick={() => changeStatus(room.id, "archived")} className="text-xs bg-amber-900 text-amber-200 px-2.5 py-1 rounded hover:bg-amber-800 transition">
                          Archive
                        </button>
                      )}
                      <button onClick={() => deleteRoom(room.id, room.name)} className="text-xs bg-red-900 text-red-200 px-2.5 py-1 rounded hover:bg-red-800 transition">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
