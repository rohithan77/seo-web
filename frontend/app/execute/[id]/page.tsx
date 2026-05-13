"use client";

import { useEffect, useState, useRef, use } from "react";
import { CheckCircle, XCircle, Loader2, Lock, ChevronRight, SkipForward, Play, Pause } from "lucide-react";

type Task = {
  id: string; week: number; title: string; description: string;
  platform_action: string; impact: number; target_url?: string; status: string;
};

type ExecStatus = {
  total: number; completed: number; pending: number; failed: number;
  progress_pct: number; next_task: Task | null; tasks: Task[];
};

type WPCreds = { url: string; username: string; password: string };

const NEEDS_WP = (action: string) => action.startsWith("wp_");

function StatusIcon({ status, running }: { status: string; running?: boolean }) {
  if (running) return <Loader2 size={16} className="animate-spin text-indigo-500" />;
  if (status === "completed") return <CheckCircle size={16} className="text-green-500" />;
  if (status === "failed") return <XCircle size={16} className="text-red-400" />;
  if (status === "skipped") return <SkipForward size={16} className="text-slate-300" />;
  return <div className="w-4 h-4 rounded-full border-2 border-slate-200" />;
}

export default function ExecutePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [status, setStatus] = useState<ExecStatus | null>(null);
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const [autoRunning, setAutoRunning] = useState(false);
  const [log, setLog] = useState<Array<{ task_id: string; action_taken: string; status: string; error?: string }>>([]);
  const [showCredsFor, setShowCredsFor] = useState<string | null>(null);
  const [creds, setCreds] = useState<WPCreds>({ url: "", username: "", password: "" });
  const [credsError, setCredsError] = useState("");
  const [autoLog, setAutoLog] = useState<string[]>([]);
  const stopRef = useRef(false);
  const credsRef = useRef<WPCreds | null>(null);

  async function refresh(): Promise<ExecStatus | null> {
    const res = await fetch(`/api/execute/${id}/status`);
    if (res.ok) {
      const data = await res.json();
      setStatus(data);
      setLog(data.log || []);
      return data;
    }
    return null;
  }

  useEffect(() => {
    refresh();
  }, [id]);

  async function runOneTask(taskId: string, wpCreds?: WPCreds): Promise<"ok" | "needs_creds" | "failed"> {
    setRunningTaskId(taskId);
    const body: Record<string, string> = { task_id: taskId };
    if (wpCreds) {
      body.wp_url = wpCreds.url;
      body.wp_username = wpCreds.username;
      body.wp_app_password = wpCreds.password;
    }
    try {
      const res = await fetch(`/api/execute/${id}/task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setRunningTaskId(null);

      if (data.needs_credentials) return "needs_creds";
      await refresh();
      return data.status === "completed" ? "ok" : "failed";
    } catch {
      setRunningTaskId(null);
      return "failed";
    }
  }

  // Single manual execute
  async function handleRunTask(taskId: string, wpCreds?: WPCreds) {
    setCredsError("");
    const result = await runOneTask(taskId, wpCreds);
    if (result === "needs_creds") {
      setShowCredsFor(taskId);
    } else {
      setShowCredsFor(null);
    }
  }

  // Core auto-run loop — runs a given list of task IDs in sequence
  async function runTaskList(taskIds: string[], addLog: (msg: string) => void) {
    for (const taskId of taskIds) {
      if (stopRef.current) break;
      const currentStatus = await refresh();
      const task = currentStatus?.tasks.find((t) => t.id === taskId);
      if (!task) continue;

      const needsWp = NEEDS_WP(task.platform_action);
      addLog(`Running: ${task.title}`);

      const wpCreds = needsWp ? credsRef.current : undefined;
      const result = await runOneTask(taskId, wpCreds || undefined);

      if (result === "needs_creds") {
        setAutoRunning(false);
        setShowCredsFor(taskId);
        addLog(`Paused — WordPress credentials needed for: ${task.title}`);
        return;
      }

      addLog(result === "ok" ? `✓ Done: ${task.title}` : `✗ Failed: ${task.title} — continuing...`);
    }

    if (!stopRef.current) addLog("All tasks processed.");
    setAutoRunning(false);
  }

  // Auto-run all pending tasks in sequence
  async function startAutoRun() {
    stopRef.current = false;
    setAutoRunning(true);
    setAutoLog([]);
    const addLog = (msg: string) => setAutoLog((prev) => [...prev, msg]);

    const current = await refresh();
    const pendingIds = (current?.tasks ?? [])
      .filter((t) => t.status === "pending")
      .map((t) => t.id);

    await runTaskList(pendingIds, addLog);
  }

  // Auto-run all skipped tasks
  async function runAllSkipped() {
    stopRef.current = false;
    setAutoRunning(true);
    setAutoLog([`Re-running skipped tasks…`]);
    const addLog = (msg: string) => setAutoLog((prev) => [...prev, msg]);

    const current = await refresh();
    const skippedIds = (current?.tasks ?? [])
      .filter((t) => t.status === "skipped")
      .map((t) => t.id);

    await runTaskList(skippedIds, addLog);
  }

  // Resume auto-run after credentials are provided
  async function submitCredsAndContinue() {
    if (!creds.url || !creds.username || !creds.password) {
      setCredsError("All fields are required.");
      return;
    }
    credsRef.current = { ...creds };
    setShowCredsFor(null);
    setCredsError("");
    await startAutoRun();
  }

  async function skipTask(taskId: string) {
    setRunningTaskId(taskId);
    await fetch(`/api/execute/${id}/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, skip: true }),
    });
    setRunningTaskId(null);
    await refresh();
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
              : `${status.completed} of ${status.total} tasks done · ${status.pending} remaining`}
          </p>
        </div>
        {!allDone && (
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
          <div
            className="h-full bg-indigo-600 rounded-full transition-all duration-500"
            style={{ width: `${status.progress_pct}%` }}
          />
        </div>
        <div className="flex gap-6 mt-3 text-xs text-slate-400">
          <span><strong className="text-green-600">{status.completed}</strong> completed</span>
          <span><strong className="text-slate-600">{status.pending}</strong> pending</span>
          {status.failed > 0 && <span><strong className="text-red-500">{status.failed}</strong> failed</span>}
        </div>
      </div>

      {/* Auto-run activity log */}
      {autoLog.length > 0 && (
        <div className="bg-slate-950 rounded-xl p-4 mb-8 font-mono text-xs text-slate-300 space-y-1 max-h-40 overflow-y-auto">
          {autoLog.map((line, i) => (
            <div key={i} className={line.startsWith("✓") ? "text-green-400" : line.startsWith("✗") ? "text-red-400" : line.startsWith("Paused") ? "text-yellow-400" : "text-slate-300"}>
              {line}
            </div>
          ))}
          {autoRunning && <div className="flex items-center gap-2 text-indigo-400"><Loader2 size={10} className="animate-spin" /> working…</div>}
        </div>
      )}

      {/* WordPress credentials form — shown when auto-run pauses OR manual execute needs creds */}
      {showCredsFor && (
        <div className="bg-white border-2 border-yellow-200 rounded-2xl p-6 shadow-sm mb-8">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-800 mb-3">
            <Lock size={14} className="text-yellow-500" />
            WordPress access needed
          </div>
          <p className="text-xs text-slate-500 mb-1">
            Task: <strong>{status.tasks.find(t => t.id === showCredsFor)?.title}</strong>
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Create a dedicated <strong>Editor</strong> user in <em>WP Admin → Users → Add New</em>,
            then generate an Application Password under that user's profile.
            Credentials are used for this task only and never stored.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
            <input
              type="text"
              placeholder="https://yoursite.com"
              value={creds.url}
              onChange={(e) => setCreds((c) => ({ ...c, url: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <input
              type="text"
              placeholder="WordPress username"
              value={creds.username}
              onChange={(e) => setCreds((c) => ({ ...c, username: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <input
              type="password"
              placeholder="Application Password"
              value={creds.password}
              onChange={(e) => setCreds((c) => ({ ...c, password: e.target.value }))}
              className="px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          {credsError && <p className="text-xs text-red-500 mb-2">{credsError}</p>}
          <div className="flex gap-2">
            <button
              onClick={submitCredsAndContinue}
              disabled={!!runningTaskId || !creds.url || !creds.username || !creds.password}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {runningTaskId ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Connect & Continue
            </button>
            <button
              onClick={() => { setShowCredsFor(null); stopRef.current = true; }}
              className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Next task card — only shown in manual mode when not auto-running */}
      {nextTask && !allDone && !autoRunning && !showCredsFor && (
        <div className="bg-white border-2 border-indigo-100 rounded-2xl p-6 shadow-sm mb-8">
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
              {nextTask.target_url && (
                <p className="text-xs text-indigo-600 mt-1">{nextTask.target_url}</p>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={() => skipTask(nextTask.id)}
                disabled={!!runningTaskId}
                className="px-3 py-2 text-xs text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg transition-colors"
              >
                Skip
              </button>
              <button
                onClick={() => handleRunTask(nextTask.id)}
                disabled={!!runningTaskId}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {runningTaskId === nextTask.id ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                Execute
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
          return (
            <div key={task.id} className="flex items-start gap-4 px-5 py-4">
              <div className="mt-0.5 shrink-0">
                <StatusIcon status={task.status} running={isRunning} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-400">{task.id}</span>
                  <span className={`text-sm font-medium ${isPending && !isRunning ? "text-slate-400" : "text-slate-800"}`}>
                    {task.title}
                  </span>
                </div>
                {logEntry?.action_taken && (
                  <p className="text-xs text-green-700 mt-0.5">{logEntry.action_taken}</p>
                )}
                {logEntry?.error && (
                  <p className="text-xs text-red-500 mt-0.5">{logEntry.error}</p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {isPending && !isRunning && !autoRunning && (
                  <button
                    onClick={() => skipTask(task.id)}
                    disabled={!!runningTaskId}
                    className="text-xs text-slate-400 hover:text-slate-600 underline underline-offset-2 transition-colors"
                  >
                    Skip
                  </button>
                )}
                {task.status === "skipped" && !autoRunning && (
                  <button
                    onClick={() => handleRunTask(task.id)}
                    disabled={!!runningTaskId}
                    className="text-xs text-indigo-500 hover:text-indigo-700 underline underline-offset-2 transition-colors"
                  >
                    Run
                  </button>
                )}
                <div className="text-xs text-slate-400 capitalize">{isRunning ? "running…" : task.status}</div>
              </div>
            </div>
          );
        })}
      </div>

      {allDone && (() => {
        const skippedTasks = status.tasks.filter((t) => t.status === "skipped");
        return (
          <>
            {skippedTasks.length > 0 && !autoRunning && (
              <div className="mt-8 bg-yellow-50 border border-yellow-100 rounded-xl p-6">
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <h3 className="font-semibold text-slate-900 mb-1">
                      {skippedTasks.length} skipped task{skippedTasks.length !== 1 ? "s" : ""}
                    </h3>
                    <p className="text-sm text-slate-500">
                      Ready to run whenever you are. Click "Run all skipped" or run them one by one above.
                    </p>
                  </div>
                  <button
                    onClick={runAllSkipped}
                    disabled={!!runningTaskId}
                    className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors shrink-0"
                  >
                    <Play size={14} /> Run all skipped
                  </button>
                </div>
              </div>
            )}
            {status.completed > 0 && (
              <div className="mt-6 bg-green-50 border border-green-100 rounded-xl p-6 text-center">
                <CheckCircle size={32} className="text-green-500 mx-auto mb-3" />
                <h3 className="font-semibold text-slate-900 mb-1">
                  {skippedTasks.length === 0 ? "All done!" : "Completed tasks done"}
                </h3>
                <p className="text-sm text-slate-500">
                  {status.completed} task{status.completed !== 1 ? "s" : ""} completed.{" "}
                  {skippedTasks.length === 0
                    ? "Your site's SEO has been improved. Re-run a new audit in 30 days to measure the impact."
                    : `Run the skipped tasks above when ready.`}
                </p>
              </div>
            )}
          </>
        );
      })()}
    </div>
  );
}
