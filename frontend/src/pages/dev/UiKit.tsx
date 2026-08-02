import { Button } from "../../components/ui/forms/Button";
import { Input } from "../../components/ui/forms/Input";
import { Textarea } from "../../components/ui/forms/Textarea";
import { Label } from "../../components/ui/forms/Label";
import { Select } from "../../components/ui/forms/Select";

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

      <section data-testid="uikit-form-fields" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Input / Textarea / Label
        </h2>
        <div className="max-w-sm space-y-3">
          <div>
            <Label htmlFor="uikit-input">Name</Label>
            <Input id="uikit-input" placeholder="Jane Doe" className="mt-1.5" />
          </div>
          <div>
            <Label htmlFor="uikit-textarea">Description</Label>
            <Textarea id="uikit-textarea" placeholder="Say something…" className="mt-1.5" />
          </div>
          <Input aria-invalid="true" defaultValue="invalid value" />
        </div>
      </section>

      <section data-testid="uikit-select" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Select
        </h2>
        <Select defaultValue="active" wrapClassName="w-56">
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="archived">Archived</option>
        </Select>
      </section>
    </div>
  );
}
