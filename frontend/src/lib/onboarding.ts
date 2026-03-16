type OnboardingProfileLike = {
  name?: string | null;
  preferred_name?: string | null;
  timezone?: string | null;
};

export function isOnboardingComplete(
  profile: OnboardingProfileLike | null | undefined,
): boolean {
  if (!profile) return false;
  const resolvedName = profile.preferred_name?.trim() || profile.name?.trim();
  return Boolean(resolvedName) && Boolean(profile.timezone?.trim());
}
