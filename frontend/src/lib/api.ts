const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Types
export interface Agent {
  id: string;
  name: string;
  connector_type: string;
  capabilities: Record<string, unknown> | null;
  created_at: string;
}

export interface Room {
  id: string;
  name: string;
  topic: string | null;
  status: string;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface RoomMember {
  agent_id: string;
  agent_name: string;
  role: string;
  joined_at: string;
}

export interface RoomDetail extends Room {
  members: RoomMember[];
}

export interface Message {
  id: string;
  room_id: string;
  agent_id: string | null;
  type: string;
  content: string;
  parent_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  offset: number;
  limit: number;
}

// Agent API
export const agentsApi = {
  list: () => request<Agent[]>("/api/agents"),
  get: (id: string) => request<Agent>(`/api/agents/${id}`),
  create: (data: { name: string; connector_type?: string; capabilities?: Record<string, unknown> }) =>
    request<Agent>("/api/agents", { method: "POST", body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/agents/${id}`, { method: "DELETE" }),
  getToken: (id: string) => request<{ agent_id: string; token: string }>(`/api/agents/${id}/token`, { method: "POST" }),
};

// Room API
export const roomsApi = {
  list: () => request<Room[]>("/api/rooms"),
  get: (id: string) => request<RoomDetail>(`/api/rooms/${id}`),
  create: (data: { name: string; topic?: string; settings?: Record<string, unknown> }) =>
    request<Room>("/api/rooms", { method: "POST", body: JSON.stringify(data) }),
  join: (roomId: string, data: { agent_id: string; role: string }) =>
    request<{ room_id: string; agent_id: string; role: string }>(`/api/rooms/${roomId}/join`, { method: "POST", body: JSON.stringify(data) }),
  leave: (roomId: string, agentId: string) =>
    request<void>(`/api/rooms/${roomId}/leave?agent_id=${agentId}`, { method: "POST" }),
  updateStatus: (roomId: string, status: string) =>
    request<Room>(`/api/rooms/${roomId}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
};

// Message API
export const messagesApi = {
  list: (roomId: string, params?: { limit?: number; offset?: number; type?: string }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    if (params?.type) qs.set("type", params.type);
    return request<MessageListResponse>(`/api/rooms/${roomId}/messages?${qs}`);
  },
  send: (roomId: string, data: { agent_id: string; type: string; content: string; parent_id?: string }) =>
    request<Message>(`/api/rooms/${roomId}/messages`, { method: "POST", body: JSON.stringify(data) }),
};

// Health
export const healthApi = {
  check: () => request<{ status: string }>("/health"),
};
