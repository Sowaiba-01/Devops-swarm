import type { Metadata, Viewport } from "next";

import { Shell } from "@/components/Shell";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Swarm Console",
    template: "%s · Swarm Console",
  },
  description:
    "Operator console for an autonomous multi-agent system that plans, implements, tests and reviews changes for GitHub issues.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
};

/**
 * Applied before first paint so the page never flashes the wrong theme. It has
 * to be inline and synchronous: a React effect runs after hydration, by which
 * point the mismatch is already on screen.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('swarm.theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || (!stored && prefersDark) || (!stored && !prefersDark && false)) {
      document.documentElement.classList.add('dark');
    } else if (stored === 'light') {
      document.documentElement.classList.remove('dark');
    } else if (!stored) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {
    document.documentElement.classList.add('dark');
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
