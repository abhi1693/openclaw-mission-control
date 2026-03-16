import { useState } from "react";

import { ApiError } from "@/api/mutator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type MarketplaceSkillFormValues = {
  sourceUrl: string;
  name: string;
  description: string;
  branch: string;
};

type MarketplaceSkillFormProps = {
  initialValues?: MarketplaceSkillFormValues;
  sourceUrlReadOnly?: boolean;
  sourceUrlHelpText?: string;
  sourceLabel?: string;
  sourcePlaceholder?: string;
  nameLabel?: string;
  namePlaceholder?: string;
  descriptionLabel?: string;
  descriptionPlaceholder?: string;
  branchLabel?: string;
  branchPlaceholder?: string;
  defaultBranch?: string;
  requiredUrlMessage?: string;
  invalidUrlMessage?: string;
  submitLabel: string;
  submittingLabel: string;
  showBranch?: boolean;
  isSubmitting: boolean;
  onCancel: () => void;
  onSubmit: (values: MarketplaceSkillFormValues) => Promise<void>;
};

const DEFAULT_VALUES: MarketplaceSkillFormValues = {
  sourceUrl: "",
  name: "",
  description: "",
  branch: "main",
};

const extractErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof ApiError) return error.message || fallback;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
};

/**
 * Form used for creating/editing a marketplace skill source.
 *
 * Intentionally keeps validation lightweight + client-side only:
 * the backend remains the source of truth and returns actionable errors.
 */
export function MarketplaceSkillForm({
  initialValues,
  sourceUrlReadOnly = false,
  sourceUrlHelpText,
  sourceLabel = "Skill URL",
  sourcePlaceholder = "https://github.com/org/skill-repo",
  nameLabel = "Name (optional)",
  namePlaceholder = "Deploy Helper",
  descriptionLabel = "Description (optional)",
  descriptionPlaceholder = "Short summary shown in the marketplace.",
  branchLabel = "Branch (optional)",
  branchPlaceholder = "main",
  defaultBranch = "main",
  showBranch = false,
  requiredUrlMessage = "Skill URL is required.",
  invalidUrlMessage = "Skill URL must be a GitHub repository URL (https://github.com/<owner>/<repo>).",
  submitLabel,
  submittingLabel,
  isSubmitting,
  onCancel,
  onSubmit,
}: MarketplaceSkillFormProps) {
  const resolvedInitial = initialValues ?? DEFAULT_VALUES;
  const normalizedDefaultBranch = defaultBranch.trim() || "main";
  const [sourceUrl, setSourceUrl] = useState(resolvedInitial.sourceUrl);
  const [name, setName] = useState(resolvedInitial.name);
  const [description, setDescription] = useState(resolvedInitial.description);
  const [branch, setBranch] = useState(
    resolvedInitial.branch?.trim() || normalizedDefaultBranch,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  /**
   * Basic repo URL validation.
   *
   * This is strict by design (https + github.com + at least owner/repo)
   * to catch obvious mistakes early. More complex URLs (subpaths, branches)
   * are handled server-side.
   */
  const isValidSourceUrl = (value: string) => {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:") return false;
      if (parsed.hostname !== "github.com") return false;
      const parts = parsed.pathname
        .split("/")
        .map((segment) => segment.trim())
        .filter((segment) => segment.length > 0);
      return parts.length >= 2;
    } catch {
      return false;
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedUrl = sourceUrl.trim();
    if (!normalizedUrl) {
      setErrorMessage(requiredUrlMessage);
      return;
    }

    if (!isValidSourceUrl(normalizedUrl)) {
      setErrorMessage(invalidUrlMessage);
      return;
    }

    setErrorMessage(null);

    try {
      await onSubmit({
        sourceUrl: normalizedUrl,
        name: name.trim(),
        description: description.trim(),
        branch: branch.trim() || normalizedDefaultBranch,
      });
    } catch (error) {
      setErrorMessage(extractErrorMessage(error, "Unable to save skill."));
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="space-y-5">
        <div className="space-y-2">
          <label
            htmlFor="source-url"
            className="text-xs font-semibold uppercase tracking-wider text-slate-500"
          >
            {sourceLabel}
          </label>
          <Input
            id="source-url"
            type="url"
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder={sourcePlaceholder}
            readOnly={sourceUrlReadOnly}
            disabled={isSubmitting || sourceUrlReadOnly}
          />
          {sourceUrlHelpText ? (
            <p className="text-xs text-slate-500">{sourceUrlHelpText}</p>
          ) : null}
        </div>

        {showBranch ? (
          <div className="space-y-2">
            <label
              htmlFor="skill-branch"
              className="text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              {branchLabel}
            </label>
            <Input
              id="skill-branch"
              value={branch}
              onChange={(event) => setBranch(event.target.value)}
              placeholder={branchPlaceholder}
              disabled={isSubmitting}
            />
          </div>
        ) : null}

        <div className="space-y-2">
          <label
            htmlFor="skill-name"
            className="text-xs font-semibold uppercase tracking-wider text-slate-500"
          >
            {nameLabel}
          </label>
          <Input
            id="skill-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={namePlaceholder}
            disabled={isSubmitting}
          />
        </div>

        <div className="space-y-2">
          <label
            htmlFor="skill-description"
            className="text-xs font-semibold uppercase tracking-wider text-slate-500"
          >
            {descriptionLabel}
          </label>
          <Textarea
            id="skill-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={descriptionPlaceholder}
            className="min-h-[120px]"
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
