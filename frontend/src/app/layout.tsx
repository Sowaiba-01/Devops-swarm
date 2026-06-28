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
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} dark`}>
      <body className="bg-[#050505] text-slate-100 min-h-screen antialiased font-mono">

        {/* Top nav */}
        <nav className="sticky top-0 z-40 border-b border-[#00ff8715] bg-[#050505]/90 backdrop-blur-md">
          <div className="max-w-7xl mx-auto px-5 h-11 flex items-center gap-3">

            <a href="/" className="flex items-center gap-2 group">
              <span className="text-[#00ff87] font-black text-sm tracking-[.14em]">SWARM</span>
              <span className="text-white/20 font-black text-sm">_</span>
              <span className="text-[#38bdf8] font-black text-sm tracking-[.14em]">AI</span>
            </a>

            <span className="text-white/10 text-xs">|</span>
            <span className="text-white/20 text-[10px] tracking-widest uppercase hidden sm:block">
              autonomous code-review engine
            </span>

            {/* Tech stack pills */}
            <div className="ml-auto flex items-center gap-2 text-[9px] tracking-wider">
              <span className="text-[#a855f7] border border-[#a855f730] px-2 py-0.5 rounded-sm">LangGraph</span>
              <span className="text-[#38bdf8] border border-[#38bdf830] px-2 py-0.5 rounded-sm">FastAPI</span>
              <span className="text-[#00ff87] border border-[#00ff8730] px-2 py-0.5 rounded-sm">E2B</span>
              <span className="text-[#f59e0b] border border-[#f59e0b30] px-2 py-0.5 rounded-sm">Groq · Llama 3.3</span>
            </div>

            {/* Status dot */}
            <div className="hidden sm:flex items-center gap-1.5 ml-3">
              <span className="h-1.5 w-1.5 rounded-full bg-[#00ff87] neon-pulse" />
              <span className="text-[9px] text-[#00ff8760] tracking-widest">ONLINE</span>
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-5 py-6">
          {children}
        </main>

        {/* Footer */}
        <footer className="border-t border-[#00ff8710] mt-8">
          <div className="max-w-7xl mx-auto px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3 text-[10px]">
              <span className="text-[#a855f7] font-bold tracking-wider">Built by Sowaiba Arshad</span>
              <span className="text-white/10">·</span>
              <span className="text-white/20">sowaibaworkspace@gmail.com</span>
            </div>
            <div className="flex items-center gap-2 text-[9px] text-white/15 tracking-wider">
              <span>LangGraph</span><span className="text-white/10">+</span>
              <span>Groq</span><span className="text-white/10">+</span>
              <span>E2B</span><span className="text-white/10">+</span>
              <span>FastAPI</span><span className="text-white/10">+</span>
              <span>Next.js</span><span className="text-white/10">+</span>
              <span>PostgreSQL</span>
            </div>
          </div>
        </footer>

      </body>
    </html>
  );
}
