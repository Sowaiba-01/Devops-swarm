import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "Swarm AI — Autonomous DevOps",
  description: "Multi-agent LangGraph swarm that autonomously resolves GitHub issues",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen antialiased relative">

        {/* Nav */}
        <nav className="sticky top-0 z-40 glass border-b border-white/[0.08]">
          <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-4">

            <a href="/" className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center">
                <span className="text-indigo-300 text-[11px] font-bold">S</span>
              </div>
              <span className="text-[#c7d2fe] font-semibold text-sm tracking-wide">Swarm AI</span>
            </a>

            <span className="text-white/10">·</span>
            <span className="text-white/30 text-xs hidden sm:block">
              Autonomous DevOps Agent
            </span>

            <div className="ml-auto flex items-center gap-2">
              {["LangGraph", "Groq", "E2B", "FastAPI"].map((t) => (
                <span key={t} className="text-[10px] text-indigo-300/60 border border-indigo-500/20 px-2 py-0.5 rounded-full hidden sm:inline">
                  {t}
                </span>
              ))}
              <div className="flex items-center gap-1.5 ml-2">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse" />
                <span className="text-[10px] text-emerald-400/70">online</span>
              </div>
            </div>

          </div>
        </nav>

        <main className="max-w-6xl mx-auto px-6 py-8 relative z-10">
          {children}
        </main>

        <footer className="relative z-10 border-t border-white/[0.06] mt-12">
          <div className="max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
            <div className="text-xs text-white/30">
              Built by <span className="text-indigo-300 font-medium">Sowaiba Arshad</span>
              <span className="text-white/15 mx-2">·</span>
              <span className="text-white/20">sowaibaworkspace@gmail.com</span>
            </div>
            <div className="text-[10px] text-white/15 hidden sm:block">
              LangGraph · Groq · E2B · FastAPI · Next.js · PostgreSQL
            </div>
          </div>
        </footer>

      </body>
    </html>
  );
}
