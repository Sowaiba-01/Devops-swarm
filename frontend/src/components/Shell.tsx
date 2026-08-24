"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cx } from "@/lib/format";

import { TriggerDialog } from "./TriggerDialog";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/runs", label: "Runs" },
];

/**
 * The current theme is held in the `dark` class on <html>, not in React state.
 *
 * Mirroring it into state would mean the server renders one value and the
 * client corrects it after hydration — a guaranteed mismatch plus a visible
 * flash. Both icons are rendered and CSS picks one, so the markup is identical
 * on both sides regardless of which theme is active.
 */
function ThemeToggle() {
  const toggle = () => {
    const root = document.documentElement;
    const next = root.classList.contains("dark") ? "light" : "dark";
    root.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem("swarm.theme", next);
    } catch {
      // Private browsing can reject writes; the toggle still works this session.
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle colour theme"
      className="rounded border border-line p-1.5 text-ink-muted hover:border-line-strong hover:text-ink"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        aria-hidden
        className="hidden dark:block"
        fill="none"
      >
        <circle cx="12" cy="12" r="4.5" fill="currentColor" />
        <path
          d="M12 1.5v2.5M12 20v2.5M4.2 4.2l1.8 1.8M18 18l1.8 1.8M1.5 12H4M20 12h2.5M4.2 19.8L6 18M18 6l1.8-1.8"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        aria-hidden
        className="block dark:hidden"
        fill="currentColor"
      >
        <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
      </svg>
    </button>
  );
}

function HealthIndicator() {
  const { data, error } = usePolling(
    () => api.health(),
    () => 30_000,
    [],
  );

  const state = error || !data ? "down" : data.database === "up" ? "up" : "degraded";
  const label =
    state === "up"
      ? `API healthy · ${data?.runs_in_flight ?? 0} in flight`
      : state === "degraded"
        ? "Database unreachable"
        : "API unreachable";

  return (
    <span className="flex items-center gap-1.5" title={label}>
      <span
        aria-hidden
        className={cx(
          "h-1.5 w-1.5 rounded-full",
          state === "up" ? "bg-pass" : state === "degraded" ? "bg-warn" : "bg-fail",
        )}
      />
      <span className="hidden text-2xs text-ink-faint sm:inline">{label}</span>
    </span>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dialogOpen, setDialogOpen] = useState(false);

  // Keyboard shortcut for the primary action, the way an operator console
  // should behave. Ignored while typing into a field.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable;
      if (typing) return;
      if (event.key === "n" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        setDialogOpen(true);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50
                   focus:rounded focus:bg-accent focus:px-3 focus:py-1.5 focus:text-accent-ink"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-30 border-b border-line bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-6 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2">
            <span
              aria-hidden
              className="grid h-6 w-6 place-items-center rounded bg-accent text-[11px] font-bold text-accent-ink"
            >
              S
            </span>
            <span className="text-[13px] font-semibold tracking-tight text-ink">
              Swarm Console
            </span>
          </Link>

          <nav aria-label="Primary" className="flex items-center gap-1">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "rounded px-2.5 py-1 text-[13px] transition-colors",
                    active
                      ? "bg-raised font-medium text-ink"
                      : "text-ink-muted hover:bg-raised/60 hover:text-ink",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <HealthIndicator />
            <ThemeToggle />
            <button type="button" onClick={() => setDialogOpen(true)} className="btn-primary">
              New run
              <kbd className="ml-1 hidden rounded bg-black/15 px-1 font-mono text-[10px] sm:inline">
                n
              </kbd>
            </button>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6">
        {children}
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-4 text-2xs text-ink-faint sm:px-6">
          <span>LangGraph · Groq · E2B · FastAPI · Next.js · PostgreSQL</span>
          <span className="ml-auto">Built by Sowaiba Arshad</span>
        </div>
      </footer>

      {dialogOpen && <TriggerDialog onClose={() => setDialogOpen(false)} />}
    </div>
  );
}
