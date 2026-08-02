import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-textarea{
  display:flex;width:100%;min-width:0;min-height:4rem;
  padding:.5rem .75rem;
  font-family:var(--font-sans);font-size:var(--text-sm);line-height:var(--text-sm-lh);
  color:var(--foreground);background:transparent;
  border:1px solid var(--input);border-radius:var(--radius-md);
  box-shadow:var(--shadow-xs);outline:none;resize:vertical;
  transition:color .15s,box-shadow .15s,border-color .15s;
}
.ds-textarea::placeholder{color:var(--muted-foreground)}
.ds-textarea:focus-visible{border-color:var(--ring);box-shadow:0 0 0 3px color-mix(in oklab,var(--ring) 50%,transparent)}
.ds-textarea:disabled{cursor:not-allowed;opacity:.5}
.ds-textarea[aria-invalid="true"]{border-color:var(--destructive);box-shadow:0 0 0 3px color-mix(in oklab,var(--destructive) 20%,transparent)}
`;

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className = "", ...props }: TextareaProps) {
  useStyle("ds-textarea", CSS);
  return <textarea data-slot="textarea" className={`ds-textarea ${className}`} {...props} />;
}
