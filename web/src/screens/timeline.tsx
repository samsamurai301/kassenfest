import { ArrowLeft } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { type PatientTimeline, type Severity, useTimeline } from '@/api/client'
import { RuleId } from '@/components/finding'
import { DEMO_MONTH, LoadError, Loading, Page } from '@/components/shell'
import { SEVERITY, SEVERITY_ORDER, SeverityBadge } from '@/components/status'
import {
  clock,
  day,
  dayNumber,
  domainShort,
  longDate,
  money,
  monthName,
  shortDate,
} from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const WEEKDAY = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const LABEL_W = 'grid-cols-[150px_minmax(0,1fr)] sm:grid-cols-[180px_minmax(0,1fr)]'

export function TimelineScreen({ id }: { id: string }) {
  const timeline = useTimeline(id)
  if (timeline.isPending) return <Loading what="the timeline" />
  if (timeline.isError) return <LoadError error={timeline.error} />
  return <TimelineView t={timeline.data} />
}

/**
 * Positions on the month axis, in percent. Calendar days, not 24-hour steps: October has
 * a 25-hour day when summer time ends.
 */
function axis(t: PatientTimeline) {
  const first = dayNumber(t.first_day)
  const days = dayNumber(t.last_day) - first + 1
  const start = day(t.first_day)
  const clampPct = (v: number) => Math.min(Math.max(v, 0), 100)
  const at = (iso: string, time?: string | null) => {
    const [h, m] = (time ?? '00:00').split(':').map(Number)
    return ((dayNumber(iso) - first + (h * 60 + m) / 1440) / days) * 100
  }
  return {
    days,
    dates: Array.from(
      { length: days },
      (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i),
    ),
    /** Whole days from..to inclusive, clipped to the month. */
    span: (from: string, to: string) => {
      const left = clampPct(at(from))
      const right = clampPct(at(to, '24:00'))
      return { left, width: right - left, clipLeft: at(from) < 0, clipRight: right >= 100 }
    },
    /** An exact moment from a naive datetime, e.g. admission at 2026-10-12T10:30. */
    moment: (iso: string) => clampPct(at(iso, iso.slice(11, 16))),
    visit: (date: string, time: string | null | undefined) => clampPct(at(date, time ?? '12:00')),
  }
}

function TimelineView({ t }: { t: PatientTimeline }) {
  const ax = axis(t)
  const holidays = new Map(t.holidays.map((h) => [h.date, h.name]))
  const hkpLogs = t.visit_logs.filter((v) => v.domain === 'sgbv')
  const needsRx = hkpLogs.length > 0
  const physician = new Map(t.physicians.map((p) => [p.lanr, p.name]))
  const grade = t.patient.pflegegrad?.at(-1)?.grade
  const visitSeverity = severityByVisit(t)

  // Days of HKP visits with no Verordnung / Genehmigung covering them.
  const covered = (periods: { period_from: string; period_to: string }[]) => (iso: string) =>
    periods.some((p) => p.period_from <= iso && iso <= p.period_to)
  const visitDays = [...new Set(hkpLogs.flatMap((l) => l.visits.map((v) => v.date)))].sort()
  const rxGaps = runs(visitDays.filter((d) => !covered(t.prescriptions)(d)))
  const approvalGaps = runs(visitDays.filter((d) => !covered(t.approvals)(d)))

  return (
    <Page>
      <BackLinks t={t} />
      <header className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[30px] leading-tight font-bold tracking-[-0.015em]">
            {t.patient.name}
          </h1>
          <p className="mt-1 text-[15px] text-graphite">
            Born {longDate(t.patient.dob)}
            <span className="mx-2 text-rule-strong">|</span>
            Versicherten-Nr.{' '}
            <span className="font-semibold text-ink tabular">{t.patient.kvnr}</span>
            {grade && (
              <>
                <span className="mx-2 text-rule-strong">|</span>
                Pflegegrad <span className="font-semibold text-ink">{grade}</span>
              </>
            )}
          </p>
        </div>
        <p className="text-[15px] font-semibold">{monthName(t.month)}</p>
      </header>

      <div className="mt-6 overflow-x-auto rounded-lg border bg-sheet">
        <div className="relative min-w-[880px]">
          {/* Weekend, holiday and stay shading behind every lane. */}
          <div className={cn('pointer-events-none absolute inset-0 grid', LABEL_W)} aria-hidden>
            <div />
            <div className="relative">
              {ax.dates.map((d, i) => {
                const iso = isoDate(d)
                const off = d.getDay() === 0 || d.getDay() === 6 || holidays.has(iso)
                return off ? (
                  <div
                    key={i}
                    className="absolute inset-y-0 bg-paper"
                    style={{ left: `${(i / ax.days) * 100}%`, width: `${100 / ax.days}%` }}
                  />
                ) : null
              })}
              {t.stays.map((s) => {
                const left = ax.moment(s.admitted_at)
                const right = s.discharged_at ? ax.moment(s.discharged_at) : 100
                return (
                  <div
                    key={s.id}
                    className="absolute inset-y-0 border-x-2 border-blocked-edge/70"
                    style={{ left: `${left}%`, width: `${right - left}%`, ...HATCH_RED }}
                  />
                )
              })}
            </div>
          </div>

          <div className={cn('relative grid border-b', LABEL_W)}>
            <div className="px-4 py-2 text-[12.5px] text-graphite">October 2026</div>
            <ol className="relative flex">
              {ax.dates.map((d, i) => {
                const iso = isoDate(d)
                const holiday = holidays.get(iso)
                return (
                  <li
                    key={i}
                    className="flex-1 py-1.5 text-center leading-tight"
                    title={holiday ?? longDate(iso)}
                  >
                    <span className="block text-[11px] text-graphite">{WEEKDAY[d.getDay()]}</span>
                    <span
                      className={cn(
                        'block text-[12.5px] font-semibold tabular',
                        holiday && 'text-stamp underline decoration-2 underline-offset-2',
                      )}
                    >
                      {d.getDate()}
                    </span>
                  </li>
                )
              })}
            </ol>
          </div>

          {needsRx && (
            <Lane label="Verordnung" hint="Prescription">
              {t.prescriptions.map((rx) => {
                const s = ax.span(rx.period_from, rx.period_to)
                const ends = s.clipRight ? '' : `, until ${shortDate(rx.period_to)}`
                return (
                  <Bar key={rx.id} {...s} className="border-stamp/45 bg-stamp-wash text-stamp">
                    {rx.kind === 'erst' ? 'Erstverordnung' : 'Folgeverordnung'},{' '}
                    {physician.get(rx.physician_lanr) ?? rx.physician_lanr}
                    {ends}
                  </Bar>
                )
              })}
              {rxGaps.map(([from, to]) => (
                <Bar
                  key={from}
                  {...ax.span(from, to)}
                  className="border-blocked-edge text-blocked"
                  style={HATCH_RED}
                >
                  No Verordnung
                </Bar>
              ))}
            </Lane>
          )}

          {needsRx && (
            <Lane label="Genehmigung" hint="Approval by the Kasse">
              {t.approvals.map((a) => (
                <Bar
                  key={a.id}
                  {...ax.span(a.period_from, a.period_to)}
                  className="border-ready-edge/50 bg-ready-wash text-ready"
                >
                  Approved, {a.approval_ref}
                </Bar>
              ))}
              {approvalGaps.map(([from, to]) => (
                <Bar
                  key={from}
                  {...ax.span(from, to)}
                  className="border-fixable-edge text-fixable"
                  style={HATCH_AMBER}
                >
                  {t.approvals.length ? 'No Genehmigung' : 'No decision from the Kasse yet'}
                </Bar>
              ))}
            </Lane>
          )}

          <Lane label="Stays" hint="Hospital, rehab, short-term care">
            {t.stays.length === 0 && (
              <span className="absolute inset-y-0 left-3 flex items-center text-[13px] text-graphite">
                None known
              </span>
            )}
            {t.stays.map((s) => {
              const left = ax.moment(s.admitted_at)
              const right = s.discharged_at ? ax.moment(s.discharged_at) : 100
              return (
                <Bar
                  key={s.id}
                  left={left}
                  width={right - left}
                  className="border-blocked-edge bg-blocked-wash text-blocked"
                  aside={`${shortDate(s.admitted_at)}, ${clock(s.admitted_at.slice(11))} to ${
                    s.discharged_at
                      ? `${shortDate(s.discharged_at)}, ${clock(s.discharged_at.slice(11))}`
                      : 'today'
                  }`}
                >
                  {STAY_KIND[s.kind]}
                </Bar>
              )
            })}
          </Lane>

          {t.visit_logs.map((log) => {
            const seen = new Map<string, { date: string; time: string; severity?: Severity }>()
            for (const v of log.visits) {
              const key = `${v.date} ${v.start}`
              const severity = visitSeverity.get(`${log.id}#${v.entry_index}`)
              const prev = seen.get(key)
              if (!prev || rank(severity) < rank(prev.severity)) {
                seen.set(key, { date: v.date, time: v.start ?? '12:00', severity })
              }
            }
            return (
              <Lane
                key={log.id}
                label={`Visits, ${domainShort[log.domain]}`}
                hint={log.domain === 'sgbv' ? 'Home nursing' : 'Care services'}
              >
                {[...seen.values()].map((v) => (
                  <VisitTick key={`${v.date}${v.time}`} left={ax.visit(v.date, v.time)} {...v} />
                ))}
              </Lane>
            )
          })}
        </div>
      </div>

      <Legend />
      <FindingsList t={t} />
    </Page>
  )
}

const HATCH_RED: CSSProperties = {
  backgroundImage:
    'repeating-linear-gradient(135deg, rgb(212 65 47 / 0.16) 0 6px, transparent 6px 12px)',
}
const HATCH_AMBER: CSSProperties = {
  backgroundImage:
    'repeating-linear-gradient(135deg, rgb(217 144 31 / 0.2) 0 6px, transparent 6px 12px)',
}

const STAY_KIND: Record<PatientTimeline['stays'][number]['kind'], string> = {
  hospital: 'In hospital',
  rehab: 'In rehab',
  short_term_care: 'Short-term care',
  hospice: 'In a hospice',
  nursing_home: 'In a nursing home',
}

const rank = (s?: Severity) => (s ? SEVERITY_ORDER.indexOf(s) : SEVERITY_ORDER.length)

function severityByVisit(t: PatientTimeline) {
  const lines = new Map(t.claims.flatMap((c) => c.lines.map((l) => [l.id, l])))
  const out = new Map<string, Severity>()
  for (const f of t.findings) {
    if (f.severity === 'info') continue
    for (const id of f.claim_line_ids ?? []) {
      const line = lines.get(id)
      if (!line?.visit_log_id) continue
      const key = `${line.visit_log_id}#${line.entry_index}`
      if (rank(f.severity) < rank(out.get(key))) out.set(key, f.severity)
    }
  }
  return out
}

/** Consecutive ISO dates -> [first, last] runs. */
function runs(dates: string[]): [string, string][] {
  const out: [string, string][] = []
  for (const d of dates) {
    const last = out.at(-1)
    if (last && dayNumber(d) - dayNumber(last[1]) === 1) last[1] = d
    else out.push([d, d])
  }
  return out
}

const isoDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function Lane({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div className={cn('relative grid border-b last:border-b-0', LABEL_W)}>
      <div className="px-4 py-2.5">
        <p className="text-[14px] font-bold" lang="de">
          {label}
        </p>
        <p className="text-[12px] text-graphite">{hint}</p>
      </div>
      <div className="relative min-h-14">{children}</div>
    </div>
  )
}

function Bar({
  left,
  width,
  clipLeft,
  clipRight,
  className,
  style,
  aside,
  children,
}: {
  left: number
  width: number
  clipLeft?: boolean
  clipRight?: boolean
  className?: string
  style?: CSSProperties
  /** Plain text right of the bar, for bars too short to hold their details. */
  aside?: string
  children: ReactNode
}) {
  return (
    <>
      <div
        className={cn(
          'absolute inset-y-2.5 flex items-center overflow-hidden rounded-md border px-2 text-[13px] font-semibold whitespace-nowrap',
          clipLeft && 'rounded-l-none border-l-0',
          clipRight && 'rounded-r-none border-r-0',
          className,
        )}
        style={{ left: `${left}%`, width: `${width}%`, ...style }}
        title={typeof children === 'string' ? children : undefined}
      >
        <span className="truncate">{children}</span>
      </div>
      {aside && (
        <span
          className="absolute inset-y-0 flex items-center pl-2 text-[13px] font-semibold whitespace-nowrap text-ink"
          style={{ left: `${left + width}%` }}
        >
          {aside}
        </span>
      )}
    </>
  )
}

function VisitTick({
  left,
  date,
  time,
  severity,
}: {
  left: number
  date: string
  time: string
  severity?: Severity
}) {
  const label = `${longDate(date)} ${clock(time)}${severity ? `, ${SEVERITY[severity].label}` : ''}`
  return (
    <span
      className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${left}%` }}
      title={label}
    >
      <TickShape severity={severity} />
      <span className="sr-only">{label}</span>
    </span>
  )
}

function TickShape({ severity }: { severity?: Severity }) {
  if (severity === 'block') {
    return (
      <svg viewBox="0 0 14 14" className="block size-3.5" aria-hidden>
        <path
          d="M3 3l8 8M11 3l-8 8"
          stroke="var(--blocked)"
          strokeWidth="2.6"
          strokeLinecap="round"
        />
      </svg>
    )
  }
  if (severity === 'warn') {
    return (
      <svg viewBox="0 0 14 14" className="block size-3.5" aria-hidden>
        <path
          d="M7 1.8l5.6 10H1.4z"
          fill="var(--fixable-edge)"
          stroke="var(--fixable)"
          strokeWidth="1"
        />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 14 14" className="block size-2.5" aria-hidden>
      <circle cx="7" cy="7" r="5.5" fill="var(--ink)" />
    </svg>
  )
}

function Legend() {
  return (
    <ul className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-graphite">
      <li className="flex items-center gap-2">
        <TickShape /> Visit
      </li>
      <li className="flex items-center gap-2">
        <TickShape severity="block" /> Visit that blocks the bill
      </li>
      <li className="flex items-center gap-2">
        <TickShape severity="warn" /> Visit with a warning
      </li>
      <li className="flex items-center gap-2">
        <span className="h-3.5 w-6 rounded-sm border border-blocked-edge" style={HATCH_RED} />
        Not billable: no cover or in hospital
      </li>
      <li className="flex items-center gap-2">
        <span className="h-3.5 w-6 rounded-sm bg-paper ring-1 ring-rule" />
        Weekend or public holiday
      </li>
    </ul>
  )
}

function BackLinks({ t }: { t: PatientTimeline }) {
  return (
    <nav className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[14px] font-semibold text-graphite">
      <Link
        to={`/months/${DEMO_MONTH}`}
        className="inline-flex items-center gap-1.5 rounded hover:text-stamp"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {monthName(t.month)} bills
      </Link>
      {t.claims.map((c) => {
        const payer = t.payers.find((p) => p.ik === c.payer_ik)
        return (
          <Link
            key={c.id}
            to={`/claims/${encodeURIComponent(c.id)}`}
            className="rounded hover:text-stamp"
          >
            Bill to {payer?.name ?? c.payer_ik}, {money(c.total_cents)}
          </Link>
        )
      })}
    </nav>
  )
}

function FindingsList({ t }: { t: PatientTimeline }) {
  if (t.findings.length === 0) {
    return (
      <p className="mt-8 text-graphite">
        No findings for {monthName(t.month)}: every visit is covered and billable.
      </p>
    )
  }
  return (
    <section aria-labelledby="timeline-findings" className="mt-8">
      <h2 id="timeline-findings" className="text-[18px] font-bold">
        What the timeline shows
      </h2>
      <ul className="mt-3 divide-y rounded-lg border bg-sheet">
        {t.findings.map((f) => (
          <li key={f.id}>
            <Link
              to={`/claims/${encodeURIComponent(f.claim_id ?? '')}`}
              className="grid gap-x-4 gap-y-1 px-4 py-3 hover:bg-stamp-wash/60 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
            >
              <span className="flex items-center gap-3">
                <SeverityBadge severity={f.severity} />
                <RuleId finding={f} />
              </span>
              <span className="text-[14px] leading-snug">{f.message_en}</span>
              {(f.amount_at_risk_cents ?? 0) > 0 && (
                <span className="text-[14px] font-bold tabular">
                  {money(f.amount_at_risk_cents ?? 0)}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
