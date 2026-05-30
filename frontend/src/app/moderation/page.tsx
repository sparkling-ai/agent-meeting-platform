"use client";

import { useEffect, useState, useCallback } from "react";
import {
  moderationApi,
  type ModerationTask,
} from "@/lib/api";

const STATUS_STYLES: Record<string, { bg: string; text: string; icon: string }> = {
  completed: { bg: "bg-emerald-900/60 border-emerald-700", text: "text-emerald-200", icon: "✓" },
  failed: { bg: "bg-red-900/60 border-red-700", text: "text-red-200", icon: "✗" },
  pending: { bg: "bg-amber-900/60 border-amber-700", text: "text-amber-200", icon: "◌" },
};

const TYPE_LABELS: Record<string, string> = {
  topic_review: "Topic Review",
  consensus_vote: "Consensus Vote",
  risk_assessment: "Risk Assessment",
};

const TYPE_COLORS: Record<string, string> = {
  topic_review: "bg-blue-900/50 text-blue-300 border-blue-700",
  consensus_vote: "bg-purple-900/50 text-purple-300 border-purple-700",
  risk_assessment: "bg-orange-900/50 text-orange-300 border-orange-700",
};

export default function ModerationPage() {
  const [tasks, setTasks] = useState<ModerationTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterType, setFilterType] = useState("");

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [taskType, setTaskType] = useState("topic_review");
  const [topic, setTopic] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  // Expanded task detail
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    try {
      const res = await moderationApi.list(
        filterType ? { task_type: filterType } : undefined
      );
      setTasks(res.tasks);
      setTotal(res.total);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const handleCreate = async () => {
    if (!topic.trim()) return;
    setCreating(true);
    try {
      await moderationApi.create({
        task_type: taskType,
        topic: topic.trim(),
        description: description.trim() || undefined,
      });
      setTopic("");
      setDescription("");
      setShowCreate(false);
      loadTasks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create task");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white">Moderation Tasks</h1>
          <p className="text-slate-400 mt-1">
            {total} task{total !== 1 ? "s" : ""} · Predefined moderation feedback
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-blue-600 text-white px-5 py-2.5 rounded-lg hover:bg-blue-700 transition font-medium"
        >
          + New Task
        </button>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-700 text-red-200 p-3 rounded-lg mb-4">
          {error}
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="bg-slate-800 p-6 rounded-xl border border-slate-700 mb-6">
          <h2 className="text-lg font-semibold mb-4 text-white">
            Create Moderation Task
          </h2>
          <div className="mb-3">
            <label className="text-xs text-slate-400 mb-1 block">Task Type</label>
            <select
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:border-blue-500 focus:outline-none"
              value={taskType}
              onChange={(e) => setTaskType(e.target.value)}
            >
              <option value="topic_review">Topic Review</option>
              <option value="consensus_vote">Consensus Vote</option>
              <option value="risk_assessment">Risk Assessment</option>
            </select>
          </div>
          <input
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-3 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none"
            placeholder="Topic for moderation"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <textarea
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 mb-4 text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none resize-none"
            placeholder="Description (optional)"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={creating || !topic.trim()}
              className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 transition disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create"}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="bg-slate-700 text-slate-300 px-5 py-2 rounded-lg hover:bg-slate-600 transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex gap-2 mb-4">
        {["", "topic_review", "consensus_vote", "risk_assessment"].map(
          (type) => (
            <button
              key={type}
              onClick={() => {
                setFilterType(type);
                setLoading(true);
              }}
              className={`px-3 py-1.5 rounded-lg text-sm transition ${
                filterType === type
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white border border-slate-700"
              }`}
            >
              {type ? TYPE_LABELS[type] : "All"}
            </button>
          )
        )}
      </div>

      {/* Task list */}
      {tasks.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg mb-2">No moderation tasks</p>
          <p className="text-slate-500">Create one to get started!</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {tasks.map((task) => {
            const status =
              STATUS_STYLES[task.status] || STATUS_STYLES["pending"];
            const isExpanded = expandedId === task.id;

            return (
              <div
                key={task.id}
                className={`bg-slate-800 rounded-xl border border-slate-700 overflow-hidden transition`}
              >
                <button
                  className="w-full text-left p-4 hover:bg-slate-750 transition"
                  onClick={() =>
                    setExpandedId(isExpanded ? null : task.id)
                  }
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium border ${
                            TYPE_COLORS[task.task_type] ||
                            "bg-slate-700 text-slate-300 border-slate-600"
                          }`}
                        >
                          {TYPE_LABELS[task.task_type] || task.task_type}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium border flex items-center gap-1 ${status.bg} ${status.text}`}
                        >
                          <span>{status.icon}</span>
                          {task.status}
                        </span>
                        <span className="text-xs text-slate-500">
                          {new Date(task.created_at).toLocaleString()}
                        </span>
                      </div>
                      <h3 className="font-semibold text-white mt-1.5 truncate">
                        {task.topic}
                      </h3>
                      {task.description && (
                        <p className="text-sm text-slate-400 mt-0.5 truncate">
                          {task.description}
                        </p>
                      )}
                    </div>
                    <span className="text-slate-500 text-sm">
                      {isExpanded ? "▲" : "▼"}
                    </span>
                  </div>
                </button>

                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-slate-700 pt-3">
                    <div className="mb-3">
                      <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
                        Expected Output
                      </h4>
                      <p className="text-sm text-slate-300 bg-slate-900/50 p-3 rounded-lg">
                        {task.expected_output}
                      </p>
                    </div>
                    <div className="flex gap-2 text-xs text-slate-500">
                      <span>ID: {task.id.slice(0, 8)}...</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
