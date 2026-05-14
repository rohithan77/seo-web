"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Zap, Mail, Lock, Loader2, ArrowRight } from "lucide-react";
import { setToken } from "@/lib/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) return;
    setLoading(true);
    setError("");

    const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/register";
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Something went wrong");
        setLoading(false);
        return;
      }
      setToken(data.token);
      router.push("/");
    } catch {
      setError("Cannot reach the server. Make sure the backend is running.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-sm">
            <Zap size={18} className="text-white" />
          </div>
          <span className="text-xl font-bold text-slate-900">SEO Agent</span>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8">
          {/* Tabs */}
          <div className="flex rounded-lg bg-slate-100 p-1 mb-6">
            {(["login", "register"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => { setMode(m); setError(""); }}
                className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-all ${
                  mode === m
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="email"
                placeholder="Email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full pl-9 pr-4 py-2.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div className="relative">
              <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                className="w-full pl-9 pr-4 py-2.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email || !password}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {loading
                ? <><Loader2 size={14} className="animate-spin" /> {mode === "login" ? "Signing in…" : "Creating account…"}</>
                : <>{mode === "login" ? "Sign in" : "Create account"} <ArrowRight size={14} /></>
              }
            </button>
          </form>

          {mode === "login" && (
            <p className="mt-4 text-center text-xs text-slate-400">
              No account?{" "}
              <button onClick={() => setMode("register")} className="text-indigo-500 hover:underline">
                Create one free
              </button>
            </p>
          )}
          {mode === "register" && (
            <p className="mt-4 text-center text-xs text-slate-400">
              Already have an account?{" "}
              <button onClick={() => setMode("login")} className="text-indigo-500 hover:underline">
                Sign in
              </button>
            </p>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          Your audits are saved to your account — access them from any device.
        </p>
      </div>
    </div>
  );
}
