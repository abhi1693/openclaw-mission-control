import type { OrganizationMemberRead } from "@/api/generated/model";

export const DEFAULT_HUMAN_LABEL = "User";

export const normalizeDisplayName = (
  value: string | null | undefined,
): string | null => {
  const trimmed = (value ?? "").trim();
  return trimmed.length > 0 ? trimmed : null;
};

export const resolveHumanActorName = (
  value: string | null | undefined,
  fallbackName: string = DEFAULT_HUMAN_LABEL,
): string => {
  const normalized = normalizeDisplayName(value);
  if (!normalized) return fallbackName;
  const lowered = normalized.toLowerCase();
  if (lowered === "admin" || lowered === "user") {
    return fallbackName;
  }
  return normalized;
};

export const resolveMemberDisplayName = (
  member: OrganizationMemberRead | null | undefined,
  fallbackName: string = DEFAULT_HUMAN_LABEL,
): string =>
  resolveHumanActorName(
    normalizeDisplayName(member?.user?.preferred_name) ??
      normalizeDisplayName(member?.user?.name),
    fallbackName,
  );
