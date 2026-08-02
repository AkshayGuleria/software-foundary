import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-select-wrap{position:relative;display:inline-flex;align-items:center;width:fit-content}
.ds-select{
  appearance:none;-webkit-appearance:none;
  display:flex;align-items:center;width:100%;height:2.25rem;
  padding:.5rem 2rem .5rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;cursor:pointer;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-select:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-select:disabled{cursor:not-allowed;opacity:.5}
.ds-select[data-size="sm"]{height:2rem}
.ds-select-icon{
  position:absolute;right:.625rem;width:1rem;height:1rem;pointer-events:none;
  color:var(--muted-foreground);
}
`;

// Same "size" collision as InputProps -- native size is a number, ours is
// a string union. Omit it.
export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size?: "default" | "sm";
  wrapClassName?: string;
}

export function Select({ className = "", size = "default", wrapClassName = "", children, ...props }: SelectProps) {
  useStyle("ds-select", CSS);
  return (
    <span className={`ds-select-wrap ${wrapClassName}`}>
      <select data-slot="select" data-size={size} className={`ds-select ${className}`} {...props}>
        {children}
      </select>
      <svg className="ds-select-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </span>
  );
}
