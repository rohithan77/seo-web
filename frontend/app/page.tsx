"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Zap, Shield, BarChart3, ArrowRight } from "lucide-react";

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/audit/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      router.push(`/audit/${data.session_id}`);
    } catch (err: unknown) {
      const isNetworkError =
        err instanceof TypeError && err.message.includes("fetch");
      setError(
        isNetworkError
          ? "Cannot reach the backend server. Make sure it is running on port 8000 — see setup instructions below."
          : `Error: ${err instanceof Error ? err.message : String(err)}`
      );
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-20 text-center">
      {/* Hero */}
      <div className="inline-flex items-center gap-2 bg-indigo-50 text-indigo-700 text-xs font-medium px-3 py-1.5 rounded-full mb-6">
        <Zap size={12} />
        Full audit in 60 seconds — no account needed
      </div>

      <h1 className="text-4xl sm:text-5xl font-bold text-slate-900 leading-tight mb-4">
        Your 30-day SEO plan,<br />
        <span className="text-indigo-600">automatically.</span>
      </h1>
      <p className="text-lg text-slate-500 mb-10 max-w-xl mx-auto">
        Paste your URL. Get a full audit across technical, content, keywords,
        backlinks, and AI visibility — then a prioritised plan you can execute task by task.
      </p>

      {/* URL form */}
      <form onSubmit={handleSubmit} className="flex gap-2 max-w-xl mx-auto">
        <div className="flex-1 relative">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://yourwebsite.com"
            className="w-full pl-10 pr-4 py-3 rounded-lg border border-slate-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent shadow-sm"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !url.trim()}
          className="flex items-center gap-2 px-5 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors shadow-sm whitespace-nowrap"
        >
          {loading ? "Starting…" : <>Analyse <ArrowRight size={14} /></>}
        </button>
      </form>

      {error && <p className="mt-3 text-sm text-red-500">{error}</p>}

      <p className="mt-4 text-xs text-slate-400">
        No login required · WordPress credentials only asked when making changes · You stay in control
      </p>

      {/* Feature pills */}
      <div className="mt-16 grid grid-cols-1 sm:grid-cols-3 gap-4 text-left">
        {[
          {
            icon: <Search size={18} className="text-indigo-500" />,
            title: "Full site audit",
            desc: "Technical, content, keywords, backlinks, competitors, and AI visibility — all in one pass.",
          },
          {
            icon: <BarChart3 size={18} className="text-indigo-500" />,
            title: "Prioritised plan",
            desc: "Scored by impact × effort. Highest-value tasks come first so you never guess what to do next.",
          },
          {
            icon: <Shield size={18} className="text-indigo-500" />,
            title: "You stay in control",
            desc: "Approve every task before it runs. Credentials asked once, per task. Never stored.",
          },
        ].map((f) => (
          <div key={f.title} className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm">
            <div className="mb-3">{f.icon}</div>
            <div className="font-semibold text-slate-800 text-sm mb-1">{f.title}</div>
            <div className="text-xs text-slate-500 leading-relaxed">{f.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
