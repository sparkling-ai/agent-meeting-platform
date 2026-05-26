import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Meeting Platform",
  description: "AI Agent collaboration and meeting rooms",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen">
        <nav className="bg-gray-900 text-white px-6 py-3 flex items-center gap-6">
          <a href="/" className="font-bold text-lg">🤝 Collab</a>
          <a href="/" className="hover:text-gray-300">Rooms</a>
          <a href="/admin/agents" className="hover:text-gray-300">Agents</a>
          <a href="/admin/rooms" className="hover:text-gray-300">Room Admin</a>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
