const HAS_TZ_RE = /[zZ]|[+-]\d\d:\d\d$/;
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Backend timestamps are emitted as ISO strings (often without a timezone).
 * Treat missing timezone info as UTC, then format in the browser's local timezone.
 */
export function normalizeApiDatetime(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  if (DATE_ONLY_RE.test(trimmed)) {
    // Convert date-only to a valid ISO timestamp.
    return `${trimmed}T00:00:00Z`;
  }
  return HAS_TZ_RE.test(trimmed) ? trimmed : `${trimmed}Z`;
}

export function parseApiDatetime(value?: string | null): Date | null {
  if (!value) return null;
  const normalized = normalizeApiDatetime(value);
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

export function apiDatetimeToMs(value?: string | null): number | null {
  const date = parseApiDatetime(value);
  return date ? date.getTime() : null;
}

export function toLocalDateInput(value?: string | null): string {
  const date = parseApiDatetime(value);
  if (!date) return "";
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function localDateInputToUtcIso(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const match = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  const day = Number(match[3]);
  const date = new Date(year, monthIndex, day);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}
