type DateParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

function preferredTimeZone(): string {
  const configured = document.documentElement.dataset.timeZone;
  if (configured) {
    try {
      new Intl.DateTimeFormat("en-GB", { timeZone: configured }).format();
      return configured;
    } catch {
      // A server-validated value is expected; retain a safe browser fallback.
    }
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function partsInZone(date: Date, timeZone: string): DateParts {
  const formatted = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const values = Object.fromEntries(
    formatted.filter((part) => part.type !== "literal").map((part) => [part.type, Number(part.value)]),
  );
  return values as DateParts;
}

const twoDigits = (value: number) => String(value).padStart(2, "0");

export function formatDate(value: string | null, includeTime = true): string {
  if (!value) return "No date set";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    ...(includeTime ? { timeStyle: "short" as const } : {}),
    timeZone: preferredTimeZone(),
  }).format(date);
}

export function toDateTimeLocal(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = partsInZone(date, preferredTimeZone());
  return `${parts.year}-${twoDigits(parts.month)}-${twoDigits(parts.day)}T${twoDigits(parts.hour)}:${twoDigits(parts.minute)}`;
}

/** Blank means no optional value; undefined means an invalid local wall time. */
export function parseOptionalDateTime(value: string): string | null | undefined {
  const input = value.trim();
  if (!input) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(input);
  if (!match) return undefined;
  const desired: DateParts = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6] ?? 0),
  };
  if (
    desired.month < 1 || desired.month > 12 || desired.day < 1 || desired.day > 31
    || desired.hour > 23 || desired.minute > 59 || desired.second > 59
  ) return undefined;

  const desiredAsUtc = Date.UTC(
    desired.year,
    desired.month - 1,
    desired.day,
    desired.hour,
    desired.minute,
    desired.second,
  );
  let candidate = desiredAsUtc;
  const timeZone = preferredTimeZone();
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const observed = partsInZone(new Date(candidate), timeZone);
    const observedAsUtc = Date.UTC(
      observed.year,
      observed.month - 1,
      observed.day,
      observed.hour,
      observed.minute,
      observed.second,
    );
    const correction = desiredAsUtc - observedAsUtc;
    if (correction === 0) break;
    candidate += correction;
  }
  const resolved = partsInZone(new Date(candidate), timeZone);
  if (Object.keys(desired).some((key) => desired[key as keyof DateParts] !== resolved[key as keyof DateParts])) {
    return undefined;
  }
  return new Date(candidate).toISOString();
}

export function today(offsetDays = 0): string {
  const current = partsInZone(new Date(), preferredTimeZone());
  return new Date(Date.UTC(current.year, current.month - 1, current.day + offsetDays))
    .toISOString()
    .slice(0, 10);
}

export const titleCase = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
