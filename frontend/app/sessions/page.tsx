"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Search, Clock, ChevronRight, Plus, CheckCircle, BarChart3, Zap } from "lucide-react";
import { apiFetch } from "@/lib/auth";

type Session = {
  session_id: string;
  url: string;
  started_at: string;
  status: "auditing" | "audited" | "planning" | "plan_ready" | "executing";
};

const STATUS_LABEL: Record<string, string> = {
  auditing: "Auditing…",
  audited: "Audit done",
  planning: "Generating plan…",
  plan_ready: "Plan ready",
  executing: "Executing",
};

const STATUS_COLOR: Record<string, string> = {
  auditing: "bg-blue-100 text-blue-700",
  audited: "bg-slate-100 text-slate-600",
  planning: "bg-yellow-100 text-yellow-700",
  plan_ready: "bg-indigo-100 text-indigo-700",
  executing: "bg-green-100 text-green-700",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function resumeHref(s: Session): string {
  if (s.status === "auditing") return `/audit/${s.session_id}`;
  if (s.status === "audited") return `/audit/${s.session_id}`;
  if (s.status === "planning" || s.status === "plan_ready") return `/plan/${s.session_id}`;
  return `/execute/${s.session_id}`;
}

export default function SessionsPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch("/api/sessions")
      .then((r) => {
        if (r.status === 401) { router.push("/login"); return null; }
        return r.json();
      })
      .then((data) => data && setSessions(data))
      .catch(() => setError("Could not load sessions"));
  }, [router]);

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Your audits</h1>
          <p className="text-sm text-slate-500 mt-1">All your saved sessions, newest first.</p>
        </div>
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus size={14} /> New audit
        </button>
      </div>

      {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

      {!sessions ? (
        <div className="flex items-center gap-2 text-slate-400 py-16 justify-center">
          <Loader2 size={18} className="animate-spin" /> Loading…
        </div>
      ) : sessions.length === 0 ? (
        <div className="bg-white border border-slate-100 rounded-2xl p-12 text-center shadow-sm">
          <Search size={32} className="text-slate-300 mx-auto mb-4" />
          <h3 className="font-semibold text-slate-700 mb-1">No audits yet</h3>
          <p className="text-sm text-slate-400 mb-4">Start your first audit to see it here.</p>
          <button
            onClick={() => router.push("/")}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg"
          >
            <Plus size={14} /> Start audit
          </button>
        </div>
      ) : (
        <div className="bg-white border border-slate-100 rounded-xl shadow-sm divide-y divide-slate-50">
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => router.push(resumeHref(s))}
              className="w-full flex items-center gap-4 px-5 py-4 hover:bg-slate-50 transition-colors text-left group"
            >
              <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
                {s.status === "executing" ? (
                  <CheckCircle size={16} className="text-green-500" />
                ) : s.status === "plan_ready" ? (
                  <BarChart3 size={16} className="text-indigo-500" />
                ) : (
                  <Zap size={16} className="text-indigo-400" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-800 truncate">{s.url}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <Clock size={11} className="text-slate-300" />
                  <span className="text-xs text-slate-400">{timeAgo(s.started_at)}</span>
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded-full ${STATUS_COLOR[s.status] ?? "bg-slate-100 text-slate-500"}`}>
                    {STATUS_LABEL[s.status] ?? s.status}
                  </span>
                </div>
              </div>
              <ChevronRight size={16} className="text-slate-300 group-hover:text-slate-500 transition-colors shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
