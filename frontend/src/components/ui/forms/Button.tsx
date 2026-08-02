import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-btn{
  display:inline-flex;align-items:center;justify-content:center;gap:.5rem;
  flex-shrink:0;white-space:nowrap;cursor:pointer;
  font-family:var(--font-sans);font-size:var(--text-sm);font-weight:500;
  line-height:var(--text-sm-lh);border-radius:var(--radius-md);
  border:1px solid transparent;outline:none;
  transition:background-color .15s ease,color .15s ease,border-color .15s ease,box-shadow .15s ease,opacity .15s ease;
}
.ds-btn svg{width:1rem;height:1rem;flex-shrink:0;pointer-events:none}
.ds-btn:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-btn:disabled{pointer-events:none;opacity:.5}
.ds-btn:active{opacity:.9}

.ds-btn[data-size="default"]{height:2.25rem;padding:.5rem 1rem}
.ds-btn[data-size="sm"]{height:2rem;padding:0 .75rem;gap:.375rem}
.ds-btn[data-size="lg"]{height:2.5rem;padding:0 1.5rem}
.ds-btn[data-size="xs"]{height:1.5rem;padding:0 .5rem;font-size:var(--text-xs);gap:.25rem}
.ds-btn[data-size="icon"]{width:2.25rem;height:2.25rem;padding:0}
.ds-btn[data-size="icon-sm"]{width:2rem;height:2rem;padding:0}
.ds-btn[data-size="icon-lg"]{width:2.5rem;height:2.5rem;padding:0}

.ds-btn[data-variant="default"]{background:var(--primary);color:var(--primary-foreground)}
.ds-btn[data-variant="default"]:hover{background:color-mix(in oklab,var(--primary) 90%,transparent)}
.ds-btn[data-variant="destructive"]{background:var(--destructive);color:#fff}
.ds-btn[data-variant="destructive"]:hover{background:color-mix(in oklab,var(--destructive) 90%,transparent)}
.ds-btn[data-variant="outline"]{background:var(--background);border-color:var(--border);box-shadow:var(--shadow-xs);color:var(--foreground)}
.ds-btn[data-variant="outline"]:hover{background:var(--accent);color:var(--accent-foreground)}
.ds-btn[data-variant="secondary"]{background:var(--secondary);color:var(--secondary-foreground)}
.ds-btn[data-variant="secondary"]:hover{background:color-mix(in oklab,var(--secondary) 80%,transparent)}
.ds-btn[data-variant="ghost"]{background:transparent;color:var(--foreground)}
.ds-btn[data-variant="ghost"]:hover{background:var(--accent);color:var(--accent-foreground)}
.ds-btn[data-variant="link"]{background:transparent;color:var(--primary);text-underline-offset:4px}
.ds-btn[data-variant="link"]:hover{text-decoration:underline}
`;

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "xs" | "icon" | "icon-sm" | "icon-lg";
}

export function Button({
  variant = "default",
  size = "default",
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  useStyle("ds-button", CSS);
  return (
    <button
      type={type}
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={`ds-btn ${className}`}
      {...props}
    />
  );
}
