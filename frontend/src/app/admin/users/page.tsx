"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi, type User } from "@/lib/api";

const roleColors: Record<string, string> = {
  admin: "bg-red-900 text-red-200",
  user: "bg-blue-900 text-blue-200",
  agent: "bg-purple-900 text-purple-200",
  viewer: "bg-slate-700 text-slate-300",
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadUsers = async () => {
    try {
      const data = await adminApi.listUsers();
      setUsers(data);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadUsers(); }, []);

  const changeRole = async (userId: string, role: string) => {
    try {
      await adminApi.updateUser(userId, { role });
      loadUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    }
  };

  const toggleActive = async (userId: string, isActive: boolean) => {
    try {
      await adminApi.updateUser(userId, { is_active: !isActive });
      loadUsers();
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
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3">
            <Link href="/" className="text-slate-400 hover:text-white transition">←</Link>
            <h1 className="text-2xl font-bold text-white">User Management</h1>
          </div>
          <p className="text-slate-400 mt-1">{users.length} users</p>
        </div>
        <span className="text-xs bg-red-900 text-red-200 px-3 py-1 rounded-full">Admin</span>
      </div>

      {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">{error}</div>}

      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left text-sm text-slate-400 px-4 py-3">User</th>
              <th className="text-left text-sm text-slate-400 px-4 py-3">Role</th>
              <th className="text-left text-sm text-slate-400 px-4 py-3">Status</th>
              <th className="text-left text-sm text-slate-400 px-4 py-3">Joined</th>
              <th className="text-right text-sm text-slate-400 px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                <td className="px-4 py-3">
                  <div>
                    <p className="text-white font-medium">{u.display_name || u.username}</p>
                    <p className="text-slate-500 text-xs">{u.email}</p>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <select
                    className={`text-xs px-2 py-1 rounded-full border-0 ${roleColors[u.role] || "bg-slate-700 text-slate-300"}`}
                    value={u.role}
                    onChange={(e) => changeRole(u.id, e.target.value)}
                  >
                    <option value="admin">admin</option>
                    <option value="user">user</option>
                    <option value="agent">agent</option>
                    <option value="viewer">viewer</option>
                  </select>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => toggleActive(u.id, u.is_active)}
                    className={`text-xs px-2 py-1 rounded-full ${
                      u.is_active ? "bg-emerald-900 text-emerald-200" : "bg-red-900 text-red-200"
                    }`}
                  >
                    {u.is_active ? "Active" : "Disabled"}
                  </button>
                </td>
                <td className="px-4 py-3 text-slate-400 text-sm">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-slate-500 text-xs">{u.id.slice(0, 8)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {users.length === 0 && (
          <div className="text-center py-12">
            <p className="text-slate-500">No users found</p>
          </div>
        )}
      </div>
    </div>
  );
}
