import { NavLink } from "react-router-dom";

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Portfolio", end: true },
  { to: "/queue", label: "Queue" },
  { to: "/projects", label: "Projects" },
  { to: "/runs", label: "Runs" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/fleet", label: "Fleet" },
  { to: "/metrics", label: "Metrics" },
  { to: "/packs", label: "Packs" },
];

export function Shell() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-shrink-0 flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)]">
      <div className="px-4 py-4 text-[var(--sidebar-foreground)]">
        <span className="text-sm font-semibold tracking-tight">Foundry</span>
      </div>
      <div className="h-px bg-[var(--sidebar-border)]" />
      <nav className="flex flex-col gap-0.5 px-2.5 py-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded-[var(--radius-md)] px-2.5 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)]"
                  : "text-[var(--sidebar-foreground)] opacity-70 hover:opacity-100 hover:bg-[var(--sidebar-accent)]"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
