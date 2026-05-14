import type { Metadata } from "next";
import "./globals.css";
import NavBar from "./NavBar";

export const metadata: Metadata = {
  title: "SEO Agent — Automated 30-Day SEO Plans",
  description: "Audit your website and get a prioritised 30-day SEO execution plan in minutes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        <NavBar />
        <main>{children}</main>
      </body>
    </html>
  );
}
