import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-badge{
  display:inline-flex;align-items:center;justify-content:center;gap:.25rem;
  width:fit-content;white-space:nowrap;
  padding:.125rem .5rem;
  font-family:var(--font-sans);font-size:var(--text-xs);font-weight:500;line-height:1.25;
  border:1px solid transparent;border-radius:var(--radius-full);
}
.ds-badge[data-variant="default"]{background:var(--primary);color:var(--primary-foreground)}
.ds-badge[data-variant="secondary"]{background:var(--secondary);color:var(--secondary-foreground)}
.ds-badge[data-variant="destructive"]{background:var(--destructive);color:#fff}
.ds-badge[data-variant="outline"]{border-color:var(--border);color:var(--foreground)}
.ds-badge[data-tone="success"]{background:color-mix(in oklab, var(--status-success) 20%, transparent);color:var(--status-success)}
.ds-badge[data-tone="warning"]{background:color-mix(in oklab, var(--status-warning) 20%, transparent);color:var(--status-warning)}
`;

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "destructive" | "outline";
  tone?: "success" | "warning";
}

export function Badge({ variant = "default", tone, className = "", ...props }: BadgeProps) {
  useStyle("ds-badge", CSS);
  return <span data-slot="badge" data-variant={variant} data-tone={tone} className={`ds-badge ${className}`} {...props} />;
}
