import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-label{
  display:inline-flex;align-items:center;gap:.5rem;
  font-family:var(--font-sans);font-size:var(--text-sm);font-weight:500;
  line-height:1;color:var(--foreground);user-select:none;
}
.ds-label[data-disabled="true"]{opacity:.5;cursor:not-allowed}
`;

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  disabled?: boolean;
}

export function Label({ className = "", disabled, ...props }: LabelProps) {
  useStyle("ds-label", CSS);
  return <label data-slot="label" data-disabled={disabled} className={`ds-label ${className}`} {...props} />;
}
