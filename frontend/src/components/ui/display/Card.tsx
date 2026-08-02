import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-card{
  background:var(--card);color:var(--card-foreground);
  border:1px solid var(--border);border-radius:var(--radius-md);
}
`;

export type CardProps = React.HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  useStyle("ds-card", CSS);
  return <div data-slot="card" className={`ds-card ${className}`} {...props} />;
}
