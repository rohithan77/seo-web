"use client";

import { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle, XCircle, Loader2, ChevronDown, ChevronUp, ArrowRight } from "lucide-react";
import { apiFetch, getToken } from "@/lib/auth";

const DOMAIN_LABELS: Record<string, string> = {
  technical: "Technical SEO",
  content: "Content Quality",
  keywords: "Keywords",
  competitors: "Competitors",
  backlinks: "Backlinks",
  ai_visibility: "AI Visibility",
};

const SEV_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  high: "bg-orange-100 text-orange-700 border-orange-200",
  medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
  low: "bg-slate-100 text-slate-600 border-slate-200",
};

const SEV_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-400",
  medium: "bg-yellow-400",
  low: "bg-slate-300",
};

type DomainStatus = { status: string; findings_count: number; error?: string };
type Finding = {
  id: string; category: string; title: string; detail: string;
  severity: string; impact: number; effort: number;
  affected_urls: string[]; recommendation: string;
};
type Report = {
  url: string; platform: string; overall_score: number;
  domains: Record<string, { score: number; findings: Finding[]; status: string }>;
  all_findings: Finding[];
};

export default function AuditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [progress, setProgress] = useState<Record<string, DomainStatus>>({});
  const [report, setReport] = useState<Report | null>(null);
  const [done, setDone] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [generatingPlan, setGeneratingPlan] = useState(false);

  // SSE stream
  useEffect(() => {
    const token = getToken();
    const es = new EventSource(`/api/audit/${id}/stream${token ? `?token=${token}` : ""}`);
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "progress") {
        setProgress((prev) => ({
          ...prev,
          [data.domain]: { status: data.status, findings_count: data.findings_count, error: data.error },
        }));
      } else if (data.type === "complete") {
        setDone(true);
        es.close();
        apiFetch(`/api/audit/${id}/report`)
          .then((r) => r.json())
          .then(setReport);
      } else if (data.type === "error") {
        setDone(true);
        es.close();
      }
    };
    return () => es.close();
  }, [id]);

  async function handleGeneratePlan() {
    setGeneratingPlan(true);
    try {
      // Kick off background generation (returns immediately)
      const res = await apiFetch(`/api/plan/${id}/generate`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`Failed to start plan generation: ${err.detail || res.status}`);
        setGeneratingPlan(false);
        return;
      }

      // Poll until plan is ready (Claude takes 30-60s)
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const poll = await apiFetch(`/api/plan/${id}`);
        if (!poll.ok) {
          const err = await poll.json().catch(() => ({}));
          alert(`Plan generation failed: ${err.detail || poll.status}`);
          setGeneratingPlan(false);
          return;
        }
        const data = await poll.json();
        if (data.status !== "generating") {
          router.push(`/plan/${id}`);
          return;
        }
      }
      alert("Plan generation timed out. Try again.");
      setGeneratingPlan(false);
    } catch {
      alert("Could not reach backend. Make sure it is running on port 8000.");
      setGeneratingPlan(false);
    }
  }

  const domainKeys = Object.keys(DOMAIN_LABELS);
  const allDone = domainKeys.every((k) => progress[k]?.status === "done" || progress[k]?.status === "error");

  function scoreColor(s: number) {
    if (s >= 70) return "text-green-600";
    if (s >= 50) return "text-yellow-600";
    return "text-red-600";
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Header */}
      <div className="mb-8">
        <div className="text-xs text-slate-400 mb-1">Session {id}</div>
        <h1 className="text-2xl font-bold text-slate-900">
          {done ? "Audit Complete" : "Auditing your site…"}
        </h1>
        {!done && (
          <p className="text-sm text-slate-500 mt-1">
            Running 6 specialist agents in parallel. This takes about 60 seconds.
          </p>
        )}
      </div>

      {/* Progress grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-10">
        {domainKeys.map((key) => {
          const d = progress[key];
          const status = d?.status ?? "waiting";
          return (
            <div key={key} className="bg-white border border-slate-100 rounded-xl p-4 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-slate-700">{DOMAIN_LABELS[key]}</span>
                {status === "running" && <Loader2 size={14} className="animate-spin text-indigo-500" />}
                {status === "done" && <CheckCircle size={14} className="text-green-500" />}
                {status === "error" && <XCircle size={14} className="text-red-400" />}
                {status === "waiting" && <div className="w-3 h-3 rounded-full bg-slate-200 pulse-dot" />}
              </div>
              <div className="text-xs text-slate-400">
                {status === "running" && "Analysing…"}
                {status === "done" && `${d.findings_count} findings`}
                {status === "error" && "Error"}
                {status === "waiting" && "Waiting"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Score overview */}
      {report && (
        <>
          <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-slate-800">Overall Score</h2>
              <span className={`text-3xl font-bold ${scoreColor(report.overall_score)}`}>
                {report.overall_score}<span className="text-lg text-slate-400">/100</span>
              </span>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {Object.entries(report.domains).map(([k, d]) => (
                <div key={k} className="text-center">
                  <div className={`text-xl font-bold ${scoreColor(d.score ?? 0)}`}>{d.score ?? "—"}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{DOMAIN_LABELS[k] ?? k}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Findings by severity */}
          {(["critical", "high", "medium", "low"] as const).map((sev) => {
            const sevFindings = report.all_findings.filter((f) => f.severity === sev);
            if (!sevFindings.length) return null;
            const isOpen = expanded[sev] ?? (sev === "critical" || sev === "high");
            return (
              <div key={sev} className="mb-4">
                <button
                  onClick={() => setExpanded((p) => ({ ...p, [sev]: !isOpen }))}
                  className="w-full flex items-center justify-between bg-white border border-slate-100 rounded-xl px-5 py-3 shadow-sm hover:bg-slate-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${SEV_DOT[sev]}`} />
                    <span className="font-medium text-slate-800 capitalize">{sev}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${SEV_COLORS[sev]}`}>
                      {sevFindings.length} issue{sevFindings.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                  {isOpen ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
                </button>

                {isOpen && (
                  <div className="border border-t-0 border-slate-100 rounded-b-xl divide-y divide-slate-50 bg-white shadow-sm">
                    {sevFindings.map((f) => (
                      <div key={f.id} className="px-5 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <div className="font-medium text-slate-800 text-sm">{f.title}</div>
                            <div className="text-xs text-slate-500 mt-0.5">{f.detail}</div>
                          </div>
                          <div className="flex gap-2 shrink-0 text-xs text-slate-400">
                            <span>Impact <strong className="text-slate-700">{f.impact}</strong></span>
                            <span>Effort <strong className="text-slate-700">{f.effort}</strong></span>
                          </div>
                        </div>
                        <div className="mt-2 text-xs text-indigo-700 bg-indigo-50 rounded-lg px-3 py-2">
                          <strong>Fix:</strong> {f.recommendation}
                        </div>
                        {f.affected_urls.length > 0 && (
                          <div className="mt-1 text-xs text-slate-400">
                            Affected: {f.affected_urls.slice(0, 3).join(", ")}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* CTA */}
          <div className="mt-8 flex justify-end">
            <button
              onClick={handleGeneratePlan}
              disabled={generatingPlan}
              className="flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg transition-colors shadow-sm"
            >
              {generatingPlan ? (
                <><Loader2 size={16} className="animate-spin" /> Generating plan…</>
              ) : (
                <>Generate 30-Day Plan <ArrowRight size={16} /></>
              )}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
