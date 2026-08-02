import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-input{
  display:flex;width:100%;min-width:0;height:2.25rem;
  padding:.25rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-input::placeholder{color:var(--muted-foreground)}
.ds-input:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-input:disabled{cursor:not-allowed;opacity:.5}
.ds-input[aria-invalid="true"]{border-color:var(--destructive);box-shadow:0 0 0 3px color-mix(in oklab,var(--destructive) 20%,transparent)}
.ds-input[data-size="sm"]{height:2rem}
`;

// Omit the native "size" attribute (a number, HTML's visual width in
// characters) -- it would otherwise conflict with our own `size` prop
// below, which takes a different type ("sm").
export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: "sm";
}

export function Input({ className = "", size, ...props }: InputProps) {
  useStyle("ds-input", CSS);
  return <input data-slot="input" data-size={size} className={`ds-input ${className}`} {...props} />;
}
