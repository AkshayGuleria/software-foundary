import * as React from "react";

/** Injects a component's CSS once (by element id), so ported primitives can
 * use real :hover/:focus-visible/:disabled selectors while staying
 * dependency-free. Shared by every primitive in components/ui/ -- do not
 * duplicate this per-component. */
export function useStyle(id: string, css: string) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement("style");
    el.id = id;
    el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}
