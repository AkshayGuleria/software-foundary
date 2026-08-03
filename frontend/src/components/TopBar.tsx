import { useEffect, useState } from "react";
import DemoModeToggle from "./DemoModeToggle";

type Theme = "dark" | "light";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = window.localStorage.getItem("foundry-theme") as Theme | null;
  if (saved === "dark" || saved === "light") return saved;
  return "dark";
}

function SunIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </svg>
  );
}

// Exported (not just used internally) so /dev/ui-kit (Task 3's gallery page)
// can render and exercise it -- see the note below on why TopBar itself
// does not mount it yet.
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
    window.localStorage.setItem("foundry-theme", theme);
  }, [theme]);

  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(next)}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
      className="inline-flex h-7 w-7 items-center justify-center rounded-[var(--radius-full)] border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]"
    >
      {theme === "dark" ? <SunIcon className="h-3.5 w-3.5" /> : <MoonIcon className="h-3.5 w-3.5" />}
    </button>
  );
}

export function TopBar() {
  return (
    // Tailwind v3 cannot apply an opacity modifier to an arbitrary var()
    // color (bg-[var(--background)]/95 silently compiles to nothing --
    // same class of failure as the @import bug Task 2 already hit). Use
    // color-mix() via an inline style instead, matching the pattern the
    // ported DS components already use throughout for hover/hover states.
    <header
      className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b border-[var(--border)] px-6 backdrop-blur-sm"
      style={{ backgroundColor: "color-mix(in oklab, var(--background) 95%, transparent)" }}
    >
      <DemoModeToggle />
      <ThemeToggle />
    </header>
  );
}
