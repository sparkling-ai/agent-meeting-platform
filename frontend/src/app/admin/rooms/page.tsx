"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { roomsApi, type Room } from "@/lib/api";

const statusColors: Record<string, string> = {
  draft: "bg-gray-200 text-gray-700",
  active: "bg-green-100 text-green-800",
  archived: "bg-yellow-100 text-yellow-800",
};

export default function RoomsAdmin() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadRooms = async () => {
    try {
      setRooms(await roomsApi.list());
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

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Room Administration</h1>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-gray-600">Name</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-gray-600">Topic</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-gray-600">Created</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rooms.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No rooms yet</td></tr>
            ) : (
              rooms.map((room) => (
                <tr key={room.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link href={`/rooms/${room.id}`} className="text-blue-600 hover:underline font-medium">
                      {room.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">{room.topic || "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[room.status]}`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(room.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {room.status !== "active" && (
                        <button onClick={() => changeStatus(room.id, "active")} className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded hover:bg-green-200">
                          Activate
                        </button>
                      )}
                      {room.status !== "archived" && (
                        <button onClick={() => changeStatus(room.id, "archived")} className="text-xs bg-yellow-100 text-yellow-700 px-2 py-1 rounded hover:bg-yellow-200">
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
