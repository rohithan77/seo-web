import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEO Agent — Automated 30-Day SEO Plans",
  description: "Audit your website and get a prioritised 30-day SEO execution plan in minutes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        <nav className="border-b border-slate-200 bg-white px-6 py-4 flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
            <span className="text-white text-xs font-bold">S</span>
          </div>
          <span className="font-semibold text-slate-900">SEO Agent</span>
          <span className="ml-auto text-xs text-slate-400">Powered by Claude</span>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
