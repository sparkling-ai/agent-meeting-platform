"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { roomsApi, type Room } from "@/lib/api";

const statusColors: Record<string, string> = {
  draft: "bg-slate-700 text-slate-300",
  active: "bg-emerald-900 text-emerald-200",
  archived: "bg-amber-900 text-amber-200",
};

export default function RoomsAdmin() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadRooms = async () => {
    try {
      setRooms(await roomsApi.list());
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

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-white mb-6">Room Administration</h1>

      {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">{error}</div>}

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Name</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Topic</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Status</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Created</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {rooms.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-slate-500">No rooms yet</td></tr>
            ) : (
              rooms.map((room) => (
                <tr key={room.id} className="hover:bg-slate-700/50 transition">
                  <td className="px-4 py-3">
                    <Link href={`/rooms/${room.id}`} className="text-blue-400 hover:text-blue-300 font-medium">
                      {room.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-400 max-w-xs truncate">{room.topic || "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusColors[room.status]}`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {new Date(room.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
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
