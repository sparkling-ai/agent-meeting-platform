import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Meeting Platform",
  description: "AI Agent collaboration and meeting rooms",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-200 min-h-screen">
        <nav className="bg-slate-900 border-b border-slate-700 px-6 py-3 flex items-center gap-6">
          <a href="/" className="font-bold text-lg text-white flex items-center gap-2">
            🤝 Agent Meetings
          </a>
          <div className="flex gap-4 ml-4">
            <a href="/" className="text-slate-300 hover:text-white transition">Rooms</a>
            <a href="/admin/agents" className="text-slate-300 hover:text-white transition">Agents</a>
            <a href="/admin/rooms" className="text-slate-300 hover:text-white transition">Admin</a>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
