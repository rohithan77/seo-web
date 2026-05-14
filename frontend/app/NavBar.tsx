"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { Zap, LayoutList, LogOut } from "lucide-react";
import { clearToken } from "@/lib/auth";

export default function NavBar() {
  const router = useRouter();
  const pathname = usePathname();

  if (pathname === "/login") return null;

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  return (
    <nav className="border-b border-slate-200 bg-white px-6 py-3.5 flex items-center gap-3">
      <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
        <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
          <Zap size={13} className="text-white" />
        </div>
        <span className="font-semibold text-slate-900">SEO Agent</span>
      </Link>

      <div className="ml-auto flex items-center gap-1">
        <Link
          href="/sessions"
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-lg transition-colors"
        >
          <LayoutList size={14} /> My audits
        </Link>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-500 hover:text-slate-800 hover:bg-slate-50 rounded-lg transition-colors"
        >
          <LogOut size={14} /> Sign out
        </button>
      </div>
    </nav>
  );
}
