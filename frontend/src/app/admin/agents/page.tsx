"use client";

import { useEffect, useState } from "react";
import { agentsApi, type Agent } from "@/lib/api";

export default function AgentsAdmin() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [connectorType, setConnectorType] = useState("rest");
  const [tokenMap, setTokenMap] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const loadAgents = async () => {
    try {
      setAgents(await agentsApi.list());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAgents(); }, []);

  const createAgent = async () => {
    if (!name.trim()) return;
    try {
      await agentsApi.create({ name: name.trim(), connector_type: connectorType });
      setName("");
      setShowCreate(false);
      loadAgents();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  };

  const getToken = async (id: string) => {
    try {
      const resp = await agentsApi.getToken(id);
      setTokenMap((prev) => ({ ...prev, [id]: resp.token }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to get token");
    }
  };

  const copyToken = (id: string) => {
    navigator.clipboard.writeText(tokenMap[id]);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  const deleteAgent = async (id: string) => {
    if (!confirm("Delete this agent?")) return;
    try {
      await agentsApi.delete(id);
      loadAgents();
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
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Agent Management</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700 transition font-medium"
        >
          + New Agent
        </button>
      </div>

      {error && <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">{error}</div>}

      {showCreate && (
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 mb-6">
          <h2 className="text-lg font-semibold mb-4 text-white">Create Agent</h2>
          <input
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-3 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none"
            placeholder="Agent name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-4 text-white focus:border-blue-500 focus:outline-none"
            value={connectorType}
            onChange={(e) => setConnectorType(e.target.value)}
          >
            <option value="rest">REST</option>
            <option value="websocket">WebSocket</option>
            <option value="webhook">Webhook</option>
          </select>
          <div className="flex gap-2">
            <button onClick={createAgent} className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 transition">Create</button>
            <button onClick={() => setShowCreate(false)} className="bg-slate-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-slate-600 transition">Cancel</button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {agents.length === 0 && (
          <div className="text-center py-12">
            <p className="text-slate-400 text-lg">No agents registered yet</p>
            <p className="text-slate-500 text-sm mt-1">Create one to get started</p>
          </div>
        )}
        {agents.map((agent) => (
          <div key={agent.id} className="bg-slate-800 p-4 rounded-xl border border-slate-700">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-white">🤖 {agent.name}</h3>
                <p className="text-sm text-slate-400 mt-1">
                  <span className="px-2 py-0.5 bg-slate-700 rounded text-xs">{agent.connector_type}</span>
                  <span className="ml-2 text-slate-500">{agent.id.slice(0, 8)}...</span>
                </p>
              </div>
              <div className="flex gap-2">
                {!tokenMap[agent.id] ? (
                  <button onClick={() => getToken(agent.id)} className="text-sm bg-slate-700 text-slate-300 px-3 py-1.5 rounded-lg hover:bg-slate-600 transition">
                    Get Token
                  </button>
                ) : (
                  <button onClick={() => copyToken(agent.id)} className="text-sm bg-emerald-900 text-emerald-200 px-3 py-1.5 rounded-lg hover:bg-emerald-800 transition">
                    {copied === agent.id ? "✓ Copied!" : "Copy Token"}
                  </button>
                )}
                <button onClick={() => deleteAgent(agent.id)} className="text-sm bg-red-900/50 text-red-300 px-3 py-1.5 rounded-lg hover:bg-red-800 transition">
                  Delete
                </button>
              </div>
            </div>
            {tokenMap[agent.id] && (
              <div className="mt-3 bg-slate-900 p-2.5 rounded-lg text-xs font-mono break-all text-slate-400 border border-slate-700">
                {tokenMap[agent.id]}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
