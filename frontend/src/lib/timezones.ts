export const fallbackTimezones = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

export function getSupportedTimezones(): string[] {
  if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
    return (
      Intl as typeof Intl & { supportedValuesOf: (key: string) => string[] }
    )
      .supportedValuesOf("timeZone")
      .sort();
  }
  return fallbackTimezones;
}
