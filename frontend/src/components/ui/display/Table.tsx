import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
.ds-table-wrap{position:relative;width:100%;overflow-x:auto}
.ds-table{width:100%;border-collapse:collapse;caption-side:bottom;font-size:var(--text-sm);color:var(--foreground)}
.ds-table-caption{margin-top:.75rem;font-size:var(--text-sm);color:var(--muted-foreground)}
.ds-thead .ds-tr{border-bottom:1px solid var(--border)}
.ds-th{
  height:2.5rem;padding:0 .625rem;text-align:left;vertical-align:middle;white-space:nowrap;
  font-weight:500;color:var(--muted-foreground);
}
.ds-tbody .ds-tr{border-bottom:1px solid var(--border);transition:background-color .1s}
.ds-tbody .ds-tr:last-child{border-bottom:none}
.ds-tbody .ds-tr:hover{background:color-mix(in oklab,var(--muted) 50%,transparent)}
.ds-tbody .ds-tr[data-state="selected"]{background:var(--muted)}
.ds-td{padding:.625rem;vertical-align:middle}
.ds-tfoot{border-top:1px solid var(--border);background:color-mix(in oklab,var(--muted) 50%,transparent);font-weight:500}
.ds-tfoot .ds-td{padding:.625rem}
`;

export interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  wrapClassName?: string;
}

export function Table({ className = "", wrapClassName = "", ...props }: TableProps) {
  useStyle("ds-table", CSS);
  return (
    <div className={`ds-table-wrap ${wrapClassName}`}>
      <table data-slot="table" className={`ds-table ${className}`} {...props} />
    </div>
  );
}
export function TableHeader({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={`ds-thead ${className}`} {...props} />;
}
export function TableBody({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={`ds-tbody ${className}`} {...props} />;
}
export function TableFooter({ className = "", ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tfoot className={`ds-tfoot ${className}`} {...props} />;
}
export function TableRow({ className = "", ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={`ds-tr ${className}`} {...props} />;
}
export function TableHead({ className = "", ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={`ds-th ${className}`} {...props} />;
}
export function TableCell({ className = "", ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={`ds-td ${className}`} {...props} />;
}
export function TableCaption({ className = "", ...props }: React.HTMLAttributes<HTMLTableCaptionElement>) {
  return <caption className={`ds-table-caption ${className}`} {...props} />;
}
