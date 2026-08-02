import * as React from "react";
import { useStyle } from "../useStyle";

const CSS = `
@keyframes ds-sheet-overlay-in{from{opacity:0}to{opacity:1}}
@keyframes ds-sheet-right{from{transform:translateX(100%)}to{transform:translateX(0)}}
@keyframes ds-sheet-left{from{transform:translateX(-100%)}to{transform:translateX(0)}}
@keyframes ds-sheet-top{from{transform:translateY(-100%)}to{transform:translateY(0)}}
@keyframes ds-sheet-bottom{from{transform:translateY(100%)}to{transform:translateY(0)}}
.ds-sheet-overlay{position:fixed;inset:0;z-index:50;background:rgb(0 0 0 / .5);animation:ds-sheet-overlay-in .2s ease}
.ds-sheet{
  position:fixed;z-index:51;display:flex;flex-direction:column;gap:1rem;
  padding:1.5rem;background:var(--background);color:var(--foreground);
  box-shadow:var(--shadow-lg);overflow-y:auto;
}
.ds-sheet[data-side="right"]{top:0;right:0;bottom:0;width:min(28rem,calc(100vw - 3rem));border-left:1px solid var(--border);animation:ds-sheet-right .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="left"]{top:0;left:0;bottom:0;width:min(28rem,calc(100vw - 3rem));border-right:1px solid var(--border);animation:ds-sheet-left .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="top"]{top:0;left:0;right:0;border-bottom:1px solid var(--border);animation:ds-sheet-top .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet[data-side="bottom"]{bottom:0;left:0;right:0;border-top:1px solid var(--border);animation:ds-sheet-bottom .3s cubic-bezier(.32,.72,0,1)}
.ds-sheet-header{display:flex;flex-direction:column;gap:.375rem;text-align:left}
.ds-sheet-title{font-size:var(--text-lg);font-weight:600;line-height:1.2;letter-spacing:-0.01em}
.ds-sheet-description{font-size:var(--text-sm);line-height:var(--text-sm-lh);color:var(--muted-foreground)}
.ds-sheet-footer{display:flex;flex-direction:column;gap:.5rem;margin-top:auto}
.ds-sheet-close{
  position:absolute;top:1rem;right:1rem;display:inline-flex;align-items:center;justify-content:center;
  width:1.5rem;height:1.5rem;cursor:pointer;color:var(--muted-foreground);
  background:transparent;border:none;border-radius:var(--radius-sm);opacity:.7;transition:opacity .15s,background-color .15s;
}
.ds-sheet-close:hover{opacity:1;background:var(--accent)}
.ds-sheet-close svg{width:1rem;height:1rem}
`;

interface SheetCtxValue {
  isOpen: boolean;
  setOpen: (v: boolean) => void;
}
const SheetCtx = React.createContext<SheetCtxValue | null>(null);

function useSheetCtx(): SheetCtxValue {
  const ctx = React.useContext(SheetCtx);
  if (!ctx) throw new Error("Sheet.* components must be rendered inside <Sheet>");
  return ctx;
}

export interface SheetProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children?: React.ReactNode;
}

export function Sheet({ open, defaultOpen = false, onOpenChange, children }: SheetProps) {
  useStyle("ds-sheet", CSS);
  const isControlled = open !== undefined;
  const [internal, setInternal] = React.useState(defaultOpen);
  const isOpen = isControlled ? open : internal;
  const setOpen = (v: boolean) => {
    if (!isControlled) setInternal(v);
    onOpenChange?.(v);
  };

  React.useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen]);

  return <SheetCtx.Provider value={{ isOpen, setOpen }}>{children}</SheetCtx.Provider>;
}

export function SheetTrigger({ asChild, children, onClick, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = useSheetCtx();
  const handleClick: React.MouseEventHandler = (e) => {
    onClick?.(e as React.MouseEvent<HTMLButtonElement>);
    ctx.setOpen(true);
  };
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<{ onClick?: React.MouseEventHandler }>;
    return React.cloneElement(child, {
      onClick: (e: React.MouseEvent) => {
        child.props.onClick?.(e);
        ctx.setOpen(true);
      },
    });
  }
  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}

export interface SheetContentProps extends React.HTMLAttributes<HTMLDivElement> {
  side?: "right" | "left" | "top" | "bottom";
  showClose?: boolean;
}

export function SheetContent({ side = "right", className = "", showClose = true, children, ...props }: SheetContentProps) {
  const ctx = useSheetCtx();
  if (!ctx.isOpen) return null;
  return (
    <React.Fragment>
      <div className="ds-sheet-overlay" onClick={() => ctx.setOpen(false)} />
      <div role="dialog" aria-modal="true" data-slot="sheet" data-side={side} className={`ds-sheet ${className}`} {...props}>
        {children}
        {showClose && (
          <button type="button" className="ds-sheet-close" aria-label="Close" onClick={() => ctx.setOpen(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </React.Fragment>
  );
}

export function SheetHeader({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`ds-sheet-header ${className}`} {...props} />;
}
export function SheetTitle({ className = "", ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={`ds-sheet-title ${className}`} {...props} />;
}
export function SheetDescription({ className = "", ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={`ds-sheet-description ${className}`} {...props} />;
}
export function SheetFooter({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`ds-sheet-footer ${className}`} {...props} />;
}
export function SheetClose({ asChild, children, onClick, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) {
  const ctx = useSheetCtx();
  const handleClick: React.MouseEventHandler = (e) => {
    onClick?.(e as React.MouseEvent<HTMLButtonElement>);
    ctx.setOpen(false);
  };
  if (asChild && React.isValidElement(children)) {
    const child = children as React.ReactElement<{ onClick?: React.MouseEventHandler }>;
    return React.cloneElement(child, {
      onClick: (e: React.MouseEvent) => {
        child.props.onClick?.(e);
        ctx.setOpen(false);
      },
    });
  }
  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}
