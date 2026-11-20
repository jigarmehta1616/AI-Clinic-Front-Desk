/** Formatting in the clinic's time zone (all API timestamps are UTC ISO strings). */

const cache = new Map<string, Intl.DateTimeFormat>();

function fmt(tz: string, options: Intl.DateTimeFormatOptions, locale = "en-IN"): Intl.DateTimeFormat {
  const key = `${locale}|${tz}|${JSON.stringify(options)}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(locale, { timeZone: tz, ...options });
    cache.set(key, f);
  }
  return f;
}

export function formatTime(iso: string, tz: string): string {
  return fmt(tz, { hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso)).toUpperCase();
}

export function formatDate(isoOrDay: string, tz: string): string {
  const d = isoOrDay.length === 10 ? new Date(`${isoOrDay}T12:00:00Z`) : new Date(isoOrDay);
  return fmt(isoOrDay.length === 10 ? "UTC" : tz, { weekday: "short", day: "numeric", month: "short" }).format(d);
}

export function formatDateTime(iso: string, tz: string): string {
  return `${formatDate(iso, tz)}, ${formatTime(iso, tz)}`;
}

/** YYYY-MM-DD of `at` in the clinic's zone. */
export function dayIn(tz: string, at: Date = new Date()): string {
  return fmt(tz, { year: "numeric", month: "2-digit", day: "2-digit" }, "en-CA").format(at);
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function monthOf(day: string): string {
  return day.slice(0, 7);
}

export function addMonths(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

export function formatMonth(month: string): string {
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(`${month}-01T12:00:00Z`),
  );
}

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export function formatMoney(paise: number): string {
  return rupees.format(Math.round(paise / 100));
}

export function minutesUntil(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.round((new Date(iso).getTime() - now.getTime()) / 60000));
}

/** +919876543210 → +91 98765 43210 */
export function formatPhone(phone: string): string {
  const m = /^\+91(\d{5})(\d{5})$/.exec(phone);
  return m ? `+91 ${m[1]} ${m[2]}` : phone;
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
