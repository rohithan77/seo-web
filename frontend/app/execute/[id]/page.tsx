"use client";

import { useEffect, useState, useRef, use } from "react";
import {
  CheckCircle, XCircle, Loader2, Lock, ChevronRight,
  SkipForward, Play, Pause, Eye, BookOpen, X, Trophy,
} from "lucide-react";
import { apiFetch } from "@/lib/auth";

type Task = {
  id: string; week: number; title: string; description: string;
  platform_action: string; impact: number; target_url?: string; status: string;
};

type ExecStatus = {
  total: number; completed: number; skipped: number; pending: number; failed: number;
  progress_pct: number; next_task: Task | null; tasks: Task[];
};

type WPCreds = { url: string; username: string; password: string };

type PreviewStep = { step: string; detail: string };

type Preview = {
  task_id: string; action: string; target_url: string; summary: string;
  current: Record<string, string>;
  suggested: Record<string, string | object | PreviewStep[]>;
  needs_credentials: boolean;
};

type ManualStep = { step: string; detail: string };

const NEEDS_WP = (action: string) => action.startsWith("wp_");

function StatusIcon({ status, running }: { status: string; running?: boolean }) {
  if (running) return <Loader2 size={18} className="animate-spin text-indigo-500" />;
  if (status === "completed") return <CheckCircle size={18} className="text-green-500 drop-shadow-sm" />;
  if (status === "failed") return <XCircle size={18} className="text-red-400" />;
  if (status === "skipped") return <SkipForward size={18} className="text-slate-300" />;
  return <div className="w-4 h-4 rounded-full border-2 border-slate-200" />;
}

// ── Preview/Approval Panel ───────────────────────────────────────────────────

function PreviewPanel({
  task, preview, onApprove, onCancel, onManual, loading,
}: {
  task: Task;
  preview: Preview | null;
  onApprove: (content: Record<string, unknown>) => void;
  onCancel: () => void;
  onManual: () => void;
  loading: boolean;
}) {
  // Editable copy of Claude's suggestions
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [editedImages, setEditedImages] = useState<Array<{ id: number; suggested_alt: string }>>([]);

  useEffect(() => {
    if (!preview) return;
    const flat: Record<string, string> = {};
    const s = preview.suggested;
    if (typeof s.meta_title === "string") flat.meta_title = s.meta_title;
    if (typeof s.meta_description === "string") flat.meta_description = s.meta_description;
    if (typeof s.canonical === "string") flat.canonical = s.canonical;
    if (typeof s.schema_json === "string") flat.schema_json = s.schema_json;
    if (typeof s.schema_type === "string") flat.schema_type = s.schema_type;
    if (typeof s.h1_title === "string") flat.h1_title = s.h1_title;
    setEdited(flat);
    if (Array.isArray(s.images)) {
      setEditedImages(s.images.map((img: { id: number; suggested_alt: string }) => ({
        id: img.id,
        suggested_alt: img.suggested_alt,
      })));
    }
  }, [preview]);

  if (loading || !preview) {
    return (
      <div className="bg-white border-2 border-indigo-100 rounded-2xl p-8 mb-8 flex items-center gap-3 text-slate-500">
        <Loader2 size={18} className="animate-spin text-indigo-400" />
        Previewing what will change…
      </div>
    );
  }

  const buildApproved = () => {
    const out: Record<string, unknown> = { ...edited };
    if (editedImages.length) out.images = editedImages;
    return out;
  };

  return (
    <div className="bg-white border-2 border-indigo-100 rounded-2xl p-6 shadow-sm mb-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="flex items-center gap-2 text-xs text-indigo-600 font-medium mb-1">
            <Eye size={13} /> Review before applying
          </div>
          <h3 className="font-semibold text-slate-900">{task.title}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{preview.summary}</p>
          {preview.target_url && (
            <p className="text-xs text-indigo-500 mt-0.5">{preview.target_url}</p>
          )}
        </div>
        <button onClick={onCancel} className="text-slate-400 hover:text-slate-600">
          <X size={18} />
        </button>
      </div>

      {/* Meta title + description */}
      {edited.meta_title !== undefined && (
        <div className="space-y-4 mb-5">
          {/* Current */}
          {preview.current.meta_title && (
            <div className="bg-slate-50 rounded-lg p-3 text-xs">
              <div className="font-medium text-slate-500 mb-1">Current meta title</div>
              <div className="text-slate-700">{preview.current.meta_title}</div>
            </div>
          )}
          {preview.current.meta_description && (
            <div className="bg-slate-50 rounded-lg p-3 text-xs">
              <div className="font-medium text-slate-500 mb-1">Current meta description</div>
              <div className="text-slate-700">{preview.current.meta_description || <span className="italic text-slate-400">none set</span>}</div>
            </div>
          )}
          {/* Editable suggestions */}
          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">
              SEO Title <span className="text-slate-400 font-normal">({edited.meta_title?.length ?? 0}/60 chars)</span>
            </label>
            <input
              type="text"
              maxLength={60}
              value={edited.meta_title ?? ""}
              onChange={(e) => setEdited((p) => ({ ...p, meta_title: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">
              Meta Description <span className="text-slate-400 font-normal">({edited.meta_description?.length ?? 0}/155 chars)</span>
            </label>
            <textarea
              maxLength={155}
              rows={3}
              value={edited.meta_description ?? ""}
              onChange={(e) => setEdited((p) => ({ ...p, meta_description: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
            />
          </div>
        </div>
      )}

      {/* H1 title */}
      {edited.h1_title !== undefined && (
        <div className="space-y-4 mb-5">
          {(preview.suggested as Record<string, unknown>).current_h1 && (
            <div className="bg-slate-50 rounded-lg p-3 text-xs">
              <div className="font-medium text-slate-500 mb-1">Current H1</div>
              <div className="text-slate-700">{String((preview.suggested as Record<string, unknown>).current_h1)}</div>
            </div>
          )}
          <div>
            <label className="text-xs font-medium text-slate-700 block mb-1">
              New H1 heading <span className="text-slate-400 font-normal">({edited.h1_title?.length ?? 0} chars)</span>
            </label>
            <input
              type="text"
              value={edited.h1_title ?? ""}
              onChange={(e) => setEdited((p) => ({ ...p, h1_title: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-slate-400 mt-1">This updates the page title (H1) directly in WordPress.</p>
          </div>
        </div>
      )}

      {/* Schema JSON */}
      {edited.schema_json !== undefined && (
        <div className="mb-5">
          <div className="bg-slate-50 rounded-lg p-3 text-xs mb-3">
            <span className="font-medium text-slate-500">Schema type: </span>
            <span className="text-indigo-700 font-mono">{edited.schema_type}</span>
            {Array.isArray(preview.suggested.existing_types) && preview.suggested.existing_types.length > 0 && (
              <span className="text-slate-400 ml-2">(existing: {(preview.suggested.existing_types as string[]).join(", ")})</span>
            )}
          </div>
          <label className="text-xs font-medium text-slate-700 block mb-1">
            JSON-LD — edit if needed
          </label>
          <textarea
            rows={10}
            value={edited.schema_json ?? ""}
            onChange={(e) => setEdited((p) => ({ ...p, schema_json: e.target.value }))}
            className="w-full px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-y"
            spellCheck={false}
          />
        </div>
      )}

      {/* Canonical */}
      {edited.canonical !== undefined && (
        <div className="mb-5">
          <label className="text-xs font-medium text-slate-700 block mb-1">Canonical URL</label>
          <input
            type="text"
            value={edited.canonical ?? ""}
            onChange={(e) => setEdited((p) => ({ ...p, canonical: e.target.value }))}
            className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>
      )}

      {/* Image alt texts */}
      {editedImages.length > 0 && (
        <div className="mb-5 space-y-3">
          <div className="text-xs font-medium text-slate-700">{editedImages.length} image(s) need alt text</div>
          {editedImages.map((img, i) => (
            <div key={img.id} className="bg-slate-50 rounded-lg p-3">
              <div className="text-xs text-slate-400 mb-1">Image {i + 1}</div>
              <input
                type="text"
                value={img.suggested_alt}
                onChange={(e) => setEditedImages((imgs) =>
                  imgs.map((x) => x.id === img.id ? { ...x, suggested_alt: e.target.value } : x)
                )}
                className="w-full px-2 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
          ))}
        </div>
      )}

      {/* Sitemap/non-editable tasks */}
      {preview.suggested.action && !edited.meta_title && !edited.schema_json && !edited.canonical && editedImages.length === 0 && !(preview.suggested as Record<string, unknown>).steps && (
        <div className="bg-indigo-50 rounded-lg p-4 mb-5 text-sm text-indigo-800">
          {String(preview.suggested.action)}
          {preview.suggested.sitemap_url && (
            <div className="font-mono text-xs mt-1 text-indigo-600">{String(preview.suggested.sitemap_url)}</div>
          )}
        </div>
      )}

      {/* Step-by-step guide for non-WP tasks */}
      {Array.isArray((preview.suggested as Record<string, unknown>).steps) && (
        <div className="mb-5">
          <div className="text-xs font-medium text-slate-500 mb-3 uppercase tracking-wide">How to complete this task</div>
          <ol className="space-y-3">
            {((preview.suggested as Record<string, unknown>).steps as Array<{step: string; detail: string}>).map((s, i) => (
              <li key={i} className="flex gap-3">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center mt-0.5">
                  {i + 1}
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-800">{s.step}</div>
                  <div className="text-xs text-slate-500 mt-0.5 whitespace-pre-line">{s.detail}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Note for non-WP tasks (only if no steps) */}
      {preview.suggested.note && !(preview.suggested as Record<string, unknown>).steps && (
        <div className="bg-amber-50 border border-amber-100 rounded-lg p-4 mb-5 text-sm text-amber-800">
          {String(preview.suggested.note)}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-slate-100">
        <button
          onClick={() => onApprove(buildApproved())}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
          Looks good — apply it
        </button>
        <button
          onClick={onManual}
          className="flex items-center gap-2 px-4 py-2 border border-slate-200 text-slate-600 hover:text-slate-800 text-sm rounded-lg transition-colors"
        >
          <BookOpen size={14} /> I&apos;ll do it myself
        </button>
        <button
          onClick={onCancel}
          className="text-sm text-slate-400 hover:text-slate-600 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Manual Instructions Panel ─────────────────────────────────────────────────

function ManualPanel({ taskId, sessionId, title, onClose, onMarkDone }: {
  taskId: string; sessionId: string; title: string;
  onClose: () => void; onMarkDone: () => void;
}) {
  const [steps, setSteps] = useState<ManualStep[] | null>(null);

  useEffect(() => {
    apiFetch(`/api/execute/${sessionId}/manual/${taskId}`)
      .then((r) => r.json())
      .then((d) => setSteps(d.instructions || []));
  }, [taskId, sessionId]);

  return (
    <div className="bg-white border-2 border-amber-200 rounded-2xl p-6 shadow-sm mb-8">
      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="flex items-center gap-2 text-xs text-amber-600 font-medium mb-1">
            <BookOpen size={13} /> Do it yourself — step by step
          </div>
          <h3 className="font-semibold text-slate-900">{title}</h3>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={18} /></button>
      </div>

      {!steps ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-4">
          <Loader2 size={14} className="animate-spin" /> Loading instructions…
        </div>
      ) : (
        <ol className="space-y-4 mb-6">
          {steps.map((s, i) => (
            <li key={i} className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-amber-100 text-amber-700 text-xs font-bold flex items-center justify-center mt-0.5">
                {i + 1}
              </div>
              <div>
                <div className="text-sm font-medium text-slate-800">{s.step}</div>
                <div className="text-xs text-slate-500 mt-0.5">{s.detail}</div>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="flex gap-3 pt-4 border-t border-slate-100">
        <button
          onClick={onMarkDone}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <CheckCircle size={14} /> Mark as done
        </button>
        <button onClick={onClose} className="text-sm text-slate-400 hover:text-slate-600">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ExecutePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [status, setStatus] = useState<ExecStatus | null>(null);
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const [autoRunning, setAutoRunning] = useState(false);
  const [log, setLog] = useState<Array<{ task_id: string; action_taken: string; status: string; error?: string }>>([]);
  const [autoLog, setAutoLog] = useState<string[]>([]);

  // Preview / approval state
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pendingApprove, setPendingApprove] = useState<((content: Record<string, unknown>) => void) | null>(null);

  // Manual instructions state
  const [manualTaskId, setManualTaskId] = useState<string | null>(null);

  // WP credentials
  const [showCredsFor, setShowCredsFor] = useState<string | null>(null);
  const [creds, setCreds] = useState<WPCreds>({ url: "", username: "", password: "" });
  const [credsError, setCredsError] = useState("");
  const credsRef = useRef<WPCreds | null>(null);

  const stopRef = useRef(false);

  async function refresh(): Promise<ExecStatus | null> {
    const res = await apiFetch(`/api/execute/${id}/status`);
    if (res.ok) {
      const data = await res.json();
      setStatus(data);
      setLog(data.log || []);
      return data;
    }
    return null;
  }

  useEffect(() => { refresh(); }, [id]);

  // ── Fetch preview for a task ─────────────────────────────────────────────
  async function fetchPreview(taskId: string, wpCreds?: WPCreds): Promise<Preview | null> {
    setPreviewLoading(true);
    setPreviewTaskId(taskId);
    setPreview(null);
    const body: Record<string, string> = { task_id: taskId };
    if (wpCreds) {
      body.wp_url = wpCreds.url;
      body.wp_username = wpCreds.username;
      body.wp_app_password = wpCreds.password;
    }
    const res = await apiFetch(`/api/execute/${id}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    setPreviewLoading(false);
    if (!res.ok) {
      // Show creds form again with error so user can correct and retry
      const msg = data?.detail || "Preview failed — check your WordPress URL and credentials.";
      setCredsError(msg);
      setPreviewTaskId(null);
      setShowCredsFor(taskId);
      return null;
    }
    setPreview(data);
    return data;
  }

  // ── Execute with approved content ────────────────────────────────────────
  async function applyTask(taskId: string, wpCreds: WPCreds | undefined, approvedContent: Record<string, unknown>): Promise<"ok" | "failed"> {
    setRunningTaskId(taskId);
    const body: Record<string, unknown> = { task_id: taskId, approved_content: approvedContent };
    if (wpCreds) {
      body.wp_url = wpCreds.url;
      body.wp_username = wpCreds.username;
      body.wp_app_password = wpCreds.password;
    }
    try {
      const res = await apiFetch(`/api/execute/${id}/task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setRunningTaskId(null);
      await refresh();
      return data.status === "completed" ? "ok" : "failed";
    } catch {
      setRunningTaskId(null);
      return "failed";
    }
  }

  // ── Manual: show instructions, then mark done ────────────────────────────
  function handleManual(taskId: string) {
    setPreviewTaskId(null);
    setPreview(null);
    setPendingApprove(null);
    setManualTaskId(taskId);
  }

  async function markManualDone(taskId: string) {
    await apiFetch(`/api/execute/${id}/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, skip: false, approved_content: { manual: true } }),
    });
    setManualTaskId(null);
    await refresh();
  }

  // ── Single task: show preview → user edits → apply ───────────────────────
  async function handleRunTask(taskId: string) {
    const task = status?.tasks.find((t) => t.id === taskId);
    if (!task) return;

    const needsWp = NEEDS_WP(task.platform_action);
    const wpCreds = needsWp ? credsRef.current || undefined : undefined;

    if (needsWp && !wpCreds) {
      // Need credentials first
      setShowCredsFor(taskId);
      return;
    }

    const p = await fetchPreview(taskId, wpCreds || undefined);
    if (!p) return; // error shown in creds form
    if (p.needs_credentials) {
      setShowCredsFor(taskId);
      return;
    }

    // Show the preview panel; approval is handled by the panel's button
    setPendingApprove(() => async (approvedContent: Record<string, unknown>) => {
      setPreviewTaskId(null);
      setPreview(null);
      setPendingApprove(null);
      await applyTask(taskId, wpCreds || undefined, approvedContent);
    });
  }

  // ── Auto-run loop ────────────────────────────────────────────────────────
  async function runTaskList(taskIds: string[], addLog: (m: string) => void) {
    for (const taskId of taskIds) {
      if (stopRef.current) break;
      const current = await refresh();
      const task = current?.tasks.find((t) => t.id === taskId);
      if (!task || task.status !== "pending") continue;

      addLog(`Previewing: ${task.title}`);
      const needsWp = NEEDS_WP(task.platform_action);
      const wpCreds = needsWp ? credsRef.current || undefined : undefined;

      if (needsWp && !wpCreds) {
        setAutoRunning(false);
        setShowCredsFor(taskId);
        addLog(`Paused — WordPress credentials needed for: ${task.title}`);
        return;
      }

      const p = await fetchPreview(taskId, wpCreds || undefined);
      if (!p || p.needs_credentials) {
        setAutoRunning(false);
        setShowCredsFor(taskId);
        addLog(`Paused — WordPress credentials needed for: ${task.title}`);
        return;
      }

      // Pause auto-run to show preview; resume is triggered by approval
      setAutoRunning(false);
      addLog(`Review required for: ${task.title}`);

      await new Promise<void>((resolve) => {
        setPendingApprove(() => async (approvedContent: Record<string, unknown>) => {
          setPreviewTaskId(null);
          setPreview(null);
          setPendingApprove(null);
          addLog(`Applying: ${task.title}`);
          const result = await applyTask(taskId, wpCreds || undefined, approvedContent);
          addLog(result === "ok" ? `✓ Done: ${task.title}` : `✗ Failed: ${task.title}`);
          resolve();
          // Resume auto-run for remaining tasks
          const remaining = taskIds.slice(taskIds.indexOf(taskId) + 1);
          if (remaining.length && !stopRef.current) {
            setAutoRunning(true);
            runTaskList(remaining, addLog);
          } else {
            addLog("All tasks processed.");
            setAutoRunning(false);
          }
        });
      });
      return; // rest continues inside the promise callback
    }

    if (!stopRef.current) addLog("All tasks processed.");
    setAutoRunning(false);
  }

  async function startAutoRun() {
    stopRef.current = false;
    setAutoRunning(true);
    setAutoLog([]);
    const addLog = (m: string) => setAutoLog((p) => [...p, m]);
    const current = await refresh();
    const pendingIds = (current?.tasks ?? []).filter((t) => t.status === "pending").map((t) => t.id);
    await runTaskList(pendingIds, addLog);
  }

  async function runAllSkipped() {
    stopRef.current = false;
    setAutoRunning(true);
    setAutoLog(["Re-running skipped tasks…"]);
    const addLog = (m: string) => setAutoLog((p) => [...p, m]);
    const current = await refresh();
    const skippedIds = (current?.tasks ?? []).filter((t) => t.status === "skipped").map((t) => t.id);
    // Reset skipped → pending before running
    for (const tid of skippedIds) {
      const task = current?.tasks.find((t) => t.id === tid);
      if (task) task.status = "pending";
    }
    await runTaskList(skippedIds, addLog);
  }

  async function skipTask(taskId: string) {
    setRunningTaskId(taskId);
    await apiFetch(`/api/execute/${id}/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, skip: true }),
    });
    setRunningTaskId(null);
    await refresh();
  }

  async function submitCredsAndContinue() {
    if (!creds.url || !creds.username || !creds.password) {
      setCredsError("All fields are required.");
      return;
    }
    credsRef.current = { ...creds };
    setShowCredsFor(null);
    setCredsError("");
    if (previewTaskId) {
      // Resume the task that triggered the creds prompt
      await handleRunTask(previewTaskId);
    } else {
      await startAutoRun();
    }
  }

  if (!status) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-indigo-500" size={24} />
      </div>
    );
  }

  const allDone = status.pending === 0;
  const nextTask = status.next_task;
  const skippedTasks = status.tasks.filter((t) => t.status === "skipped");

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            {allDone ? "All tasks complete" : "Executing Your Plan"}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {allDone
              ? `${status.completed} of ${status.total} tasks completed.`
              : `${status.completed} done · ${status.pending} remaining`}
          </p>
        </div>
        {!allDone && !previewTaskId && !manualTaskId && (
          <div className="flex gap-2">
            {autoRunning ? (
              <button
                onClick={() => { stopRef.current = true; setAutoRunning(false); }}
                className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Pause size={14} /> Pause
              </button>
            ) : (
              <button
                onClick={startAutoRun}
                disabled={!!runningTaskId}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Play size={14} /> Run All
              </button>
            )}
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm mb-8">
        <div className="flex justify-between text-sm mb-2">
          <span className="font-medium text-slate-700">Progress</span>
          <span className="text-slate-400">{status.progress_pct}%</span>
        </div>
        <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
          <div className="h-full bg-indigo-600 rounded-full transition-all duration-500" style={{ width: `${status.progress_pct}%` }} />
        </div>
        <div className="flex gap-6 mt-3 text-xs text-slate-400">
          <span><strong className="text-green-600">{status.completed}</strong> completed</span>
          <span><strong className="text-slate-600">{status.pending}</strong> pending</span>
          {status.skipped > 0 && <span><strong className="text-slate-400">{status.skipped}</strong> skipped</span>}
          {status.failed > 0 && <span><strong className="text-red-500">{status.failed}</strong> failed</span>}
        </div>
      </div>

      {/* Activity log */}
      {autoLog.length > 0 && (
        <div className="bg-slate-950 rounded-xl p-4 mb-8 font-mono text-xs text-slate-300 space-y-1 max-h-40 overflow-y-auto">
          {autoLog.map((line, i) => (
            <div key={i} className={
              line.startsWith("✓") ? "text-green-400" :
              line.startsWith("✗") ? "text-red-400" :
              line.startsWith("Paused") || line.startsWith("Review") ? "text-yellow-400" :
              "text-slate-300"
            }>{line}</div>
          ))}
          {autoRunning && <div className="flex items-center gap-2 text-indigo-400"><Loader2 size={10} className="animate-spin" /> working…</div>}
        </div>
      )}

      {/* WP Credentials form */}
      {showCredsFor && (
        <div className="bg-white border-2 border-yellow-200 rounded-2xl p-6 shadow-sm mb-8">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-800 mb-2">
            <Lock size={14} className="text-yellow-500" /> WordPress access needed
          </div>
          <p className="text-xs text-slate-500 mb-1">
            Task: <strong>{status.tasks.find((t) => t.id === showCredsFor)?.title}</strong>
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Create a dedicated <strong>Editor</strong> user in <em>WP Admin → Users → Add New</em>, generate an Application Password.
            Credentials are used for this task only and never stored.
            <button onClick={() => { setShowCredsFor(null); setManualTaskId(showCredsFor); }}
              className="ml-2 text-indigo-500 underline">
              Prefer to do it yourself?
            </button>
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
            <input type="text" placeholder="https://yoursite.com" value={creds.url}
              onChange={(e) => setCreds((c) => ({ ...c, url: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            <input type="text" placeholder="WordPress username" value={creds.username}
              onChange={(e) => setCreds((c) => ({ ...c, username: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            <input type="password" placeholder="Application Password" value={creds.password}
              onChange={(e) => setCreds((c) => ({ ...c, password: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          {credsError && <p className="text-xs text-red-500 mb-2">{credsError}</p>}
          <div className="flex gap-2">
            <button onClick={submitCredsAndContinue} disabled={!!runningTaskId || !creds.url || !creds.username || !creds.password}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
              {runningTaskId ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Connect & Preview
            </button>
            <button onClick={() => setShowCredsFor(null)}
              className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Preview panel */}
      {previewTaskId && !showCredsFor && !manualTaskId && (() => {
        const task = status.tasks.find((t) => t.id === previewTaskId);
        if (!task) return null;
        return (
          <PreviewPanel
            task={task}
            preview={preview}
            loading={previewLoading}
            onApprove={(content) => pendingApprove?.(content)}
            onCancel={() => { setPreviewTaskId(null); setPreview(null); setPendingApprove(null); }}
            onManual={() => handleManual(previewTaskId)}
          />
        );
      })()}

      {/* Manual instructions panel */}
      {manualTaskId && (() => {
        const task = status.tasks.find((t) => t.id === manualTaskId);
        if (!task) return null;
        return (
          <ManualPanel
            taskId={manualTaskId}
            sessionId={id}
            title={task.title}
            onClose={() => setManualTaskId(null)}
            onMarkDone={() => markManualDone(manualTaskId)}
          />
        );
      })()}

      {/* Next task card — manual mode, no active panel */}
      {nextTask && !allDone && !autoRunning && !previewTaskId && !manualTaskId && !showCredsFor && (
        <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm mb-8">
          <div className="flex items-center gap-2 text-xs text-indigo-600 font-medium mb-3">
            <ChevronRight size={14} /> Next task
          </div>
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-xs text-slate-400">{nextTask.id}</span>
                <span className="font-semibold text-slate-900">{nextTask.title}</span>
              </div>
              <p className="text-sm text-slate-500">{nextTask.description}</p>
              {nextTask.target_url && <p className="text-xs text-indigo-500 mt-1">{nextTask.target_url}</p>}
            </div>
            <div className="flex gap-2 shrink-0">
              <button onClick={() => skipTask(nextTask.id)} disabled={!!runningTaskId}
                className="px-3 py-2 text-xs text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg">
                Skip
              </button>
              <button onClick={() => handleManual(nextTask.id)} disabled={!!runningTaskId}
                className="flex items-center gap-1.5 px-3 py-2 text-xs text-slate-600 hover:text-slate-800 border border-slate-200 rounded-lg">
                <BookOpen size={12} /> Do myself
              </button>
              <button onClick={() => handleRunTask(nextTask.id)} disabled={!!runningTaskId}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
                {runningTaskId === nextTask.id ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
                Preview & Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Task list */}
      <div className="bg-white border border-slate-100 rounded-xl shadow-sm divide-y divide-slate-50">
        {status.tasks.map((task) => {
          const logEntry = log.find((l) => l.task_id === task.id);
          const isRunning = runningTaskId === task.id;
          const isPending = task.status === "pending";
          const isSkipped = task.status === "skipped";
          const isCompleted = task.status === "completed";
          const isFailed = task.status === "failed";
          return (
            <div
              key={task.id}
              className={`flex items-start gap-4 px-5 py-4 transition-colors ${
                isCompleted ? "bg-green-50/60" : isFailed ? "bg-red-50/40" : ""
              }`}
            >
              <div className="mt-0.5 shrink-0">
                <StatusIcon status={task.status} running={isRunning} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-400">{task.id}</span>
                  <span className={`text-sm font-medium ${
                    isCompleted ? "text-green-800" :
                    isFailed ? "text-red-700" :
                    isPending && !isRunning ? "text-slate-400" :
                    "text-slate-800"
                  }`}>
                    {task.title}
                  </span>
                </div>
                {logEntry?.action_taken && <p className="text-xs text-green-700 mt-0.5">{logEntry.action_taken}</p>}
                {logEntry?.error && <p className="text-xs text-red-500 mt-0.5">{logEntry.error}</p>}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {isPending && !isRunning && !autoRunning && (
                  <>
                    <button onClick={() => handleManual(task.id)} disabled={!!runningTaskId}
                      title="Do it yourself"
                      className="text-xs text-slate-400 hover:text-slate-600 transition-colors">
                      <BookOpen size={13} />
                    </button>
                    <button onClick={() => skipTask(task.id)} disabled={!!runningTaskId}
                      className="text-xs text-slate-400 hover:text-slate-600 underline underline-offset-2 transition-colors">
                      Skip
                    </button>
                  </>
                )}
                {isSkipped && !autoRunning && (
                  <button onClick={() => handleRunTask(task.id)} disabled={!!runningTaskId}
                    className="text-xs text-indigo-500 hover:text-indigo-700 underline underline-offset-2 transition-colors">
                    Run
                  </button>
                )}
                {isCompleted && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 text-xs font-medium rounded-full">
                    <CheckCircle size={11} /> Done
                  </span>
                )}
                {isFailed && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-100 text-red-600 text-xs font-medium rounded-full">
                    <XCircle size={11} /> Failed
                  </span>
                )}
                {isRunning && (
                  <span className="text-xs text-indigo-500 italic">running…</span>
                )}
                {isPending && !isRunning && (
                  <span className="text-xs text-slate-400">pending</span>
                )}
                {isSkipped && (
                  <span className="text-xs text-slate-400">skipped</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Skipped tasks banner + done state */}
      {allDone && (
        <>
          {skippedTasks.length > 0 && !autoRunning && (
            <div className="mt-8 bg-yellow-50 border border-yellow-100 rounded-xl p-6">
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                  <h3 className="font-semibold text-slate-900 mb-1">
                    {skippedTasks.length} skipped task{skippedTasks.length !== 1 ? "s" : ""}
                  </h3>
                  <p className="text-sm text-slate-500">
                    Click "Run all skipped" to review each one, or run them individually above.
                  </p>
                </div>
                <button onClick={runAllSkipped} disabled={!!runningTaskId}
                  className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors shrink-0">
                  <Play size={14} /> Run all skipped
                </button>
              </div>
            </div>
          )}
          {status.completed > 0 && skippedTasks.length === 0 && (
            <div className="mt-6 bg-gradient-to-br from-green-50 to-emerald-50 border border-green-200 rounded-2xl p-8 text-center shadow-sm">
              <div className="flex justify-center mb-4">
                <div className="relative">
                  <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
                    <Trophy size={30} className="text-green-600" />
                  </div>
                  <div className="absolute -top-1 -right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                    <CheckCircle size={14} className="text-white" />
                  </div>
                </div>
              </div>
              <h3 className="text-xl font-bold text-slate-900 mb-2">All done!</h3>
              <p className="text-sm text-slate-600 mb-1">
                {status.completed} task{status.completed !== 1 ? "s" : ""} completed successfully.
              </p>
              <p className="text-xs text-slate-400">Re-run a new audit in 30 days to measure the SEO impact.</p>
            </div>
          )}
          {status.completed > 0 && skippedTasks.length > 0 && (
            <div className="mt-6 bg-green-50 border border-green-100 rounded-xl p-6 text-center">
              <CheckCircle size={28} className="text-green-500 mx-auto mb-3" />
              <h3 className="font-semibold text-slate-900 mb-1">Completed tasks done</h3>
              <p className="text-sm text-slate-500">
                {status.completed} task{status.completed !== 1 ? "s" : ""} completed. Run the skipped tasks above when ready.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
