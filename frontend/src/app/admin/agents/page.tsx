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

  if (loading) return <div className="p-8 text-center text-gray-500">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Agent Management</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
        >
          + New Agent
        </button>
      </div>

      {error && <div className="bg-red-50 text-red-700 p-3 rounded mb-4">{error}</div>}

      {showCreate && (
        <div className="bg-white p-6 rounded-lg shadow mb-6 border">
          <h2 className="text-lg font-semibold mb-3">Create Agent</h2>
          <input
            className="w-full border rounded px-3 py-2 mb-3"
            placeholder="Agent name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select
            className="w-full border rounded px-3 py-2 mb-3"
            value={connectorType}
            onChange={(e) => setConnectorType(e.target.value)}
          >
            <option value="rest">REST</option>
            <option value="websocket">WebSocket</option>
            <option value="webhook">Webhook</option>
          </select>
          <div className="flex gap-2">
            <button onClick={createAgent} className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">Create</button>
            <button onClick={() => setShowCreate(false)} className="bg-gray-200 px-4 py-2 rounded hover:bg-gray-300">Cancel</button>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {agents.length === 0 && (
          <p className="text-gray-500 text-center py-8">No agents registered yet.</p>
        )}
        {agents.map((agent) => (
          <div key={agent.id} className="bg-white p-4 rounded-lg shadow border">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold">{agent.name}</h3>
                <p className="text-sm text-gray-500">Connector: {agent.connector_type} · ID: {agent.id.slice(0, 8)}...</p>
              </div>
              <div className="flex gap-2">
                {!tokenMap[agent.id] ? (
                  <button onClick={() => getToken(agent.id)} className="text-sm bg-gray-100 px-3 py-1 rounded hover:bg-gray-200">
                    Get Token
                  </button>
                ) : (
                  <button onClick={() => copyToken(agent.id)} className="text-sm bg-green-100 text-green-800 px-3 py-1 rounded hover:bg-green-200">
                    {copied === agent.id ? "✓ Copied!" : "Copy Token"}
                  </button>
                )}
                <button onClick={() => deleteAgent(agent.id)} className="text-sm bg-red-100 text-red-700 px-3 py-1 rounded hover:bg-red-200">
                  Delete
                </button>
              </div>
            </div>
            {tokenMap[agent.id] && (
              <div className="mt-2 bg-gray-50 p-2 rounded text-xs font-mono break-all">
                {tokenMap[agent.id]}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
