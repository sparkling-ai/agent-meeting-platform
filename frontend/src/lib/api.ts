const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Global auth token for API calls
let _authToken: string | null = null;

export function setAuthToken(token: string | null) {
  _authToken = token;
  if (typeof window !== "undefined") {
    if (token) localStorage.setItem("auth_token", token);
    else localStorage.removeItem("auth_token");
  }
}

export function getAuthToken(): string | null {
  if (_authToken) return _authToken;
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("auth_token");
    if (stored) { _authToken = stored; return stored; }
  }
  return null;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Types
export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

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
  visibility: string;
  max_participants: number;
  owner_id: string | null;
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

export interface ModeratorState {
  room_id: string;
  status: string;
  current_phase: string | null;
  current_item: string | null;
  phases: Array<{ name: string; status: string }>;
  started_at: string | null;
}

export interface Decision {
  id: string;
  room_id: string;
  content: string;
  decided_by: string | null;
  created_at: string;
}

export interface ActionItem {
  id: string;
  room_id: string;
  content: string;
  assignee: string | null;
  status: string;
  created_at: string;
}

export interface ModerationTask {
  id: string;
  task_type: string;
  topic: string;
  description: string | null;
  status: string;
  expected_output: string;
  created_at: string;
}

export interface ModerationTaskListResponse {
  tasks: ModerationTask[];
  total: number;
}

// Auth API
export const authApi = {
  register: (data: { username: string; email: string; password: string; display_name?: string }) =>
    request<{ access_token: string; user: User }>("/api/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data: { username: string; password: string }) =>
    request<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),
  me: () => request<User>("/api/auth/me"),
};

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
  create: (data: { name: string; topic?: string; visibility?: string; max_participants?: number; settings?: Record<string, unknown> }) =>
    request<Room>("/api/rooms", { method: "POST", body: JSON.stringify(data) }),
  join: (roomId: string, data: { agent_id: string; role: string }) =>
    request<{ room_id: string; agent_id: string; role: string }>(`/api/rooms/${roomId}/join`, { method: "POST", body: JSON.stringify(data) }),
  leave: (roomId: string, agentId: string) =>
    request<void>(`/api/rooms/${roomId}/leave?agent_id=${agentId}`, { method: "POST" }),
  activate: (roomId: string) =>
    request<Room>(`/api/rooms/${roomId}/activate`, { method: "POST" }),
  close: (roomId: string) =>
    request<Room>(`/api/rooms/${roomId}/close`, { method: "POST" }),
  updateStatus: (roomId: string, status: string) =>
    request<Room>(`/api/rooms/${roomId}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
  invite: (roomId: string, data: { agent_id: string; role: string }) =>
    request<{ detail: string; agent_id: string; role: string }>(`/api/rooms/${roomId}/invite`, { method: "POST", body: JSON.stringify(data) }),
  kick: (roomId: string, agentId: string) =>
    request<{ detail: string; agent_id: string }>(`/api/rooms/${roomId}/members/${agentId}`, { method: "DELETE" }),
  updateRole: (roomId: string, agentId: string, role: string) =>
    request<{ detail: string; old_role: string; new_role: string }>(`/api/rooms/${roomId}/members/${agentId}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
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

// Moderator API
export const moderatorApi = {
  getState: (roomId: string) => request<ModeratorState>(`/api/rooms/${roomId}/moderator/state`),
  start: (roomId: string) => request<any>(`/api/rooms/${roomId}/moderator/start`, { method: "POST" }),
  advance: (roomId: string) => request<any>(`/api/rooms/${roomId}/moderator/advance`, { method: "POST" }),
  vote: (roomId: string, data?: { proposal_id?: string }) =>
    request<any>(`/api/rooms/${roomId}/moderator/vote`, { method: "POST", body: JSON.stringify(data || {}) }),
  close: (roomId: string) => request<any>(`/api/rooms/${roomId}/moderator/close`, { method: "POST" }),
};

// Decisions & Action Items
export const decisionsApi = {
  list: (roomId: string) => request<Decision[]>(`/api/rooms/${roomId}/decisions`),
};

export const actionItemsApi = {
  list: (roomId: string) => request<ActionItem[]>(`/api/rooms/${roomId}/action-items`),
};

// Admin API
export const adminApi = {
  stats: () => request<any>("/api/admin/stats"),
  listUsers: () => request<User[]>("/api/admin/users"),
  updateUser: (userId: string, data: { role?: string; is_active?: boolean }) =>
    request<User>(`/api/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(data) }),
  listRooms: () => request<any[]>("/api/admin/rooms"),
  deleteRoom: (roomId: string) => request<{ detail: string }>(`/api/admin/rooms/${roomId}`, { method: "DELETE" }),
};

// Health
export const healthApi = {
  check: () => request<{ status: string }>("/health"),
};

// Moderation API
export const moderationApi = {
  list: (params?: { task_type?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.task_type) qs.set("task_type", params.task_type);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    return request<ModerationTaskListResponse>(`/api/moderation/predefined_task?${qs}`);
  },
  get: (id: string) => request<ModerationTask>(`/api/moderation/predefined_task/${id}`),
  create: (data: { task_type: string; topic: string; description?: string }) =>
    request<ModerationTask>("/api/moderation/predefined_task", { method: "POST", body: JSON.stringify(data) }),
};
