"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import { CheckSquare, Square, ArrowRight, Loader2, Calendar, Zap } from "lucide-react";

type Task = {
  id: string; week: number; title: string; description: string;
  platform_action: string; impact: number; effort: number;
  priority_score: number; estimated_minutes: number;
  target_url?: string; status: string;
};

type Plan = { url: string; platform: string; tasks: Task[]; detail?: string };

const WEEK_LABELS: Record<number, { label: string; color: string }> = {
  1: { label: "Week 1 — Technical Foundation", color: "border-red-200 bg-red-50" },
  2: { label: "Week 2 — On-Page Optimisation", color: "border-orange-200 bg-orange-50" },
  3: { label: "Week 3 — Content Improvements", color: "border-yellow-200 bg-yellow-50" },
  4: { label: "Week 4 — Off-Page & AI Visibility", color: "border-blue-200 bg-blue-50" },
};

function impactBadge(impact: number) {
  if (impact >= 8) return "bg-red-100 text-red-700";
  if (impact >= 6) return "bg-orange-100 text-orange-700";
  return "bg-slate-100 text-slate-600";
}

export default function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    fetch(`/api/plan/${id}`)
      .then((r) => r.json())
      .then(setPlan);
  }, [id]);

  function toggleSkip(taskId: string) {
    setSkipped((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  async function handleApprove() {
    setApproving(true);
    await fetch(`/api/plan/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skip_task_ids: Array.from(skipped) }),
    });
    router.push(`/execute/${id}`);
  }

  if (!plan) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-indigo-500" size={24} />
      </div>
    );
  }

  // API returned an error object instead of a plan
  if (plan.detail || !Array.isArray(plan.tasks)) {
    return (
      <div className="max-w-xl mx-auto px-6 py-20 text-center">
        <p className="text-red-500 font-medium mb-2">Plan not ready</p>
        <p className="text-sm text-slate-500">
          {plan.detail || "The plan has no tasks. Go back and try generating it again."}
        </p>
        <button
          onClick={() => window.history.back()}
          className="mt-6 px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg"
        >
          ← Back to report
        </button>
      </div>
    );
  }

  const weeks = [1, 2, 3, 4];
  const totalTasks = plan.tasks.length;
  const selectedTasks = totalTasks - skipped.size;
  const totalMins = plan.tasks
    .filter((t) => !skipped.has(t.id))
    .reduce((s, t) => s + t.estimated_minutes, 0);

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="mb-8">
        <div className="text-xs text-slate-400 mb-1">{plan.url} · {plan.platform}</div>
        <h1 className="text-2xl font-bold text-slate-900">Your 30-Day SEO Plan</h1>
        <p className="text-sm text-slate-500 mt-1">
          Review each task. Uncheck any you want to skip, then approve to start executing.
        </p>
      </div>

      {/* Summary bar */}
      <div className="bg-white border border-slate-100 rounded-xl p-4 shadow-sm mb-8 flex gap-6">
        <div>
          <div className="text-2xl font-bold text-slate-900">{selectedTasks}</div>
          <div className="text-xs text-slate-400">tasks selected</div>
        </div>
        <div className="border-l border-slate-100 pl-6">
          <div className="text-2xl font-bold text-slate-900">{Math.round(totalMins / 60 * 10) / 10}h</div>
          <div className="text-xs text-slate-400">estimated time</div>
        </div>
        <div className="border-l border-slate-100 pl-6">
          <div className="text-2xl font-bold text-slate-900">{plan.platform}</div>
          <div className="text-xs text-slate-400">platform</div>
        </div>
        <div className="ml-auto flex items-center">
          <button
            onClick={handleApprove}
            disabled={approving || selectedTasks === 0}
            className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            {approving ? <Loader2 size={14} className="animate-spin" /> : <><Zap size={14} /> Approve & Execute</>}
          </button>
        </div>
      </div>

      {/* Tasks by week */}
      {weeks.map((week) => {
        const weekTasks = plan.tasks.filter((t) => t.week === week);
        if (!weekTasks.length) return null;
        const { label, color } = WEEK_LABELS[week];
        return (
          <div key={week} className="mb-8">
            <div className={`flex items-center gap-2 text-sm font-semibold px-4 py-2 rounded-t-xl border ${color} mb-0`}>
              <Calendar size={14} />
              {label}
              <span className="ml-auto font-normal text-xs opacity-70">{weekTasks.length} tasks</span>
            </div>
            <div className="border border-t-0 border-slate-100 rounded-b-xl divide-y divide-slate-50 bg-white shadow-sm">
              {weekTasks.map((task) => {
                const isSkipped = skipped.has(task.id);
                return (
                  <div
                    key={task.id}
                    className={`flex items-start gap-4 px-5 py-4 transition-opacity ${isSkipped ? "opacity-40" : ""}`}
                  >
                    <button
                      onClick={() => toggleSkip(task.id)}
                      className="mt-0.5 shrink-0 text-indigo-600"
                    >
                      {isSkipped ? <Square size={18} /> : <CheckSquare size={18} />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-mono text-slate-400">{task.id}</span>
                        <span className="font-medium text-slate-800 text-sm">{task.title}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${impactBadge(task.impact)}`}>
                          Impact {task.impact}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5">{task.description}</p>
                      {task.target_url && (
                        <p className="text-xs text-indigo-600 mt-0.5 truncate">{task.target_url}</p>
                      )}
                    </div>
                    <div className="text-xs text-slate-400 shrink-0 text-right">
                      <div>{task.estimated_minutes}min</div>
                      <div className="text-slate-300">effort {task.effort}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* Bottom approve CTA */}
      <div className="flex justify-end mt-4">
        <button
          onClick={handleApprove}
          disabled={approving || selectedTasks === 0}
          className="flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg transition-colors shadow-sm"
        >
          {approving ? (
            <><Loader2 size={16} className="animate-spin" /> Starting…</>
          ) : (
            <>Approve {selectedTasks} Tasks & Execute <ArrowRight size={16} /></>
          )}
        </button>
      </div>
    </div>
  );
}
