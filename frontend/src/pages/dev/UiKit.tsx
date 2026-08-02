import { Button } from "../../components/ui/forms/Button";

/**
 * Living reference for every DS-ported primitive in this app. Not linked
 * from the nav (dev-only route) -- visit /dev/ui-kit directly. Each
 * Foundation task appends its own section here.
 */
export default function UiKit() {
  return (
    <div className="mx-auto max-w-4xl space-y-10 p-8">
      <h1 className="text-2xl font-semibold text-[var(--foreground)]">UI Kit</h1>

      <section data-testid="uikit-button" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Button
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">Link</Button>
          <Button size="sm">Small</Button>
          <Button size="lg">Large</Button>
          <Button disabled>Disabled</Button>
        </div>
      </section>
    </div>
  );
}
