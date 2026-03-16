import { useMemo, useState } from "react";

import { ApiError } from "@/api/mutator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export type TagFormValues = {
  name: string;
  slug: string;
  color: string;
  description: string;
};

type TagFormProps = {
  initialValues?: TagFormValues;
  onSubmit: (values: {
    name: string;
    slug: string;
    color: string;
    description: string | null;
  }) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
  submittingLabel: string;
  isSubmitting: boolean;
};

const DEFAULT_VALUES: TagFormValues = {
  name: "",
  slug: "",
  color: "9e9e9e",
  description: "",
};

const normalizeColorInput = (value: string) => {
  const cleaned = value.trim().replace(/^#/, "").toLowerCase();
  return /^[0-9a-f]{6}$/.test(cleaned) ? cleaned : "9e9e9e";
};

const slugify = (value: string) =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

const extractErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof ApiError) return error.message || fallback;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
};

export function TagForm({
  initialValues,
  onSubmit,
  onCancel,
  submitLabel,
  submittingLabel,
  isSubmitting,
}: TagFormProps) {
  const resolvedInitial = initialValues ?? DEFAULT_VALUES;
  const [name, setName] = useState(() => resolvedInitial.name);
  const [slug, setSlug] = useState(() => resolvedInitial.slug);
  const [color, setColor] = useState(() =>
    normalizeColorInput(resolvedInitial.color),
  );
  const [description, setDescription] = useState(
    () => resolvedInitial.description,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const previewColor = useMemo(() => normalizeColorInput(color), [color]);
  const suggestedSlug = useMemo(() => slugify(name.trim()), [name]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setErrorMessage("Tag name is required.");
      return;
    }
    const normalizedSlug = slugify(slug.trim() || normalizedName);
    if (!normalizedSlug) {
      setErrorMessage("Tag slug is required.");
      return;
    }
    setErrorMessage(null);
    try {
      await onSubmit({
        name: normalizedName,
        slug: normalizedSlug,
        color: normalizeColorInput(color),
        description: description.trim() || null,
      });
    } catch (error) {
      setErrorMessage(extractErrorMessage(error, "Unable to save tag."));
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="space-y-5">
        <div className="rounded-xl border border-slate-200 bg-slate-50/40 p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Name
              </label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Backend"
                disabled={isSubmitting}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Slug
                </label>
                <button
                  type="button"
                  onClick={() => setSlug(suggestedSlug)}
                  className="text-xs font-medium text-slate-500 underline underline-offset-2 transition hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!suggestedSlug || isSubmitting}
                >
                  Use from name
                </button>
              </div>
              <Input
                value={slug}
                onChange={(event) => setSlug(event.target.value)}
                placeholder="backend"
                disabled={isSubmitting}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Leave slug blank to auto-generate from the tag name.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-[1fr_auto]">
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Color
            </label>
            <div className="flex items-center rounded-lg border border-slate-200 bg-white px-3">
              <span className="text-sm font-medium text-slate-400">#</span>
              <Input
                value={color}
                onChange={(event) => setColor(event.target.value)}
                placeholder="9e9e9e"
                disabled={isSubmitting}
                className="border-0 px-2 shadow-none focus-visible:ring-0"
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Preview
            </label>
            <div className="inline-flex h-[42px] items-center gap-2 rounded-lg border border-slate-200 bg-white px-3">
              <span
                className="h-4 w-4 rounded border border-slate-300"
                style={{ backgroundColor: `#${previewColor}` }}
              />
              <span className="text-xs font-semibold text-slate-700">
                #{previewColor.toUpperCase()}
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Description
          </label>
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Optional description"
            className="min-h-[110px]"
            disabled={isSubmitting}
          />
        </div>

        {errorMessage ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {errorMessage}
          </div>
        ) : null}
      </div>

      <div className="flex justify-end gap-3">
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? submittingLabel : submitLabel}
        </Button>
      </div>
    </form>
  );
}
