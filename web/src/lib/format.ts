// English UI (docs/05 §2): en-GB dates, euro amounts; German text stays German.

const euro = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR' })

export const money = (cents: number) => euro.format(cents / 100)

/** Parses 'YYYY-MM-DD' as a local calendar date (no timezone shift). */
export function day(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

const fmt = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-GB', options)
const dayMonth = fmt({ day: 'numeric', month: 'short' })
const weekdayDayMonth = fmt({ weekday: 'short', day: 'numeric', month: 'short' })
const fullDate = fmt({ day: 'numeric', month: 'short', year: 'numeric' })
const monthYear = fmt({ month: 'long', year: 'numeric' })

export const shortDate = (iso: string) => dayMonth.format(day(iso))
export const weekdayDate = (iso: string) => weekdayDayMonth.format(day(iso))
export const longDate = (iso: string) => fullDate.format(day(iso))
export const monthName = (month: string) => monthYear.format(day(`${month}-01`))

/** '07:30:00' -> '07:30' */
export const clock = (time: string | null | undefined) => (time ? time.slice(0, 5) : '')

/** Day number of an ISO date in UTC: calendar arithmetic that DST can't shift. */
export function dayNumber(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Date.UTC(y, m - 1, d) / 86_400_000
}

export const daysBetween = (fromIso: string, toIso: string) => dayNumber(toIso) - dayNumber(fromIso)

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export const domainLabel = { sgbv: 'Home nursing (SGB V)', sgbxi: 'Care (SGB XI)' } as const
export const domainShort = { sgbv: 'SGB V', sgbxi: 'SGB XI' } as const
