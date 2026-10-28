import { ArrowLeft, CalendarDays, FileText } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type ClaimDetail,
  type ClaimLine,
  type DocumentInfo,
  type Finding,
  type Severity,
  useClaim,
} from '@/api/client'
import { DueChip, FindingCard } from '@/components/finding'
import { DEMO_MONTH, LoadError, Loading, Page } from '@/components/shell'
import { SEVERITY_ORDER, SeverityMark, StatusBadge, STATUS } from '@/components/status'
import { clock, domainLabel, money, monthName, plural, weekdayDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

export const DOC_TYPE: Record<DocumentInfo['doc_type'], string> = {
  muster12: 'Verordnung (Muster 12)',
  approval_letter: 'Genehmigung',
  visit_log_sgbv: 'Leistungsnachweis SGB V',
  visit_log_sgbxi: 'Leistungsnachweis SGB XI',
  hospital_letter: 'Entlassbrief',
  other: 'Other document',
}

export const docTypeLabel = (doc: DocumentInfo) => DOC_TYPE[doc.doc_type]

export function ClaimScreen({ id }: { id: string }) {
  const claim = useClaim(id)
  if (claim.isPending) return <Loading what="the bill" />
  if (claim.isError) return <LoadError error={claim.error} />
  return <ClaimView detail={claim.data} />
}

function ClaimView({ detail }: { detail: ClaimDetail }) {
  const { claim, patient, payer, findings } = detail
  const [activeId, setActiveId] = useState<string | null>(null)
  const docs = useMemo(
    () => Object.fromEntries(detail.documents.map((d) => [d.id, d])),
    [detail.documents],
  )
  const worst = useMemo(() => worstSeverityByLine(findings), [findings])
  const active = findings.find((f) => f.id === activeId)
  const highlighted = new Set(active?.claim_line_ids ?? [])
  const risky = detail.at_risk_cents > 0
  const tone = STATUS[detail.status]

  return (
    <Page>
      <Link
        to={`/months/${DEMO_MONTH}`}
        className="inline-flex items-center gap-1.5 rounded text-[14px] font-semibold text-graphite hover:text-stamp"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {monthName(claim.month)} bills
      </Link>

      <header className="mt-4 flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[30px] leading-tight font-bold tracking-[-0.015em]">
              {patient.name}
            </h1>
            <StatusBadge status={detail.status} className="text-[14px]" />
          </div>
          <p className="mt-1.5 text-[15px] text-graphite">
            {payer.name}, {domainLabel[claim.domain]}, {monthName(claim.month)}
          </p>
          <p className="mt-0.5 text-[13.5px] text-graphite">
            Versicherten-Nr. <span className="font-semibold text-ink tabular">{patient.kvnr}</span>
            <span className="mx-2 text-rule-strong">|</span>
            IK <span className="font-semibold text-ink tabular">{payer.ik}</span>
          </p>
        </div>
        <dl className="flex gap-8">
          <div>
            <dt className="text-[13px] text-graphite">Bill total</dt>
            <dd className="text-[24px] font-bold">{money(claim.total_cents)}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-graphite">At risk</dt>
            <dd className={cn('text-[24px] font-bold', risky ? tone.text : 'text-ink')}>
              {money(detail.at_risk_cents)}
            </dd>
          </div>
          <div>
            <dt className="text-[13px] text-graphite">Lines</dt>
            <dd className="text-[24px] font-bold">{claim.lines.length}</dd>
          </div>
        </dl>
      </header>

      <div className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,500px)]">
        <div className="flex min-w-0 flex-col gap-8">
          <section aria-labelledby="findings-title">
            <h2 id="findings-title" className="text-[18px] font-bold">
              {findings.length === 0 ? 'No findings' : `Findings (${findings.length})`}
            </h2>
            {findings.length === 0 ? (
              <p className="mt-2 max-w-[60ch] text-graphite">
                Every line passed the rules for {monthName(claim.month)}. This bill is ready to
                send.
              </p>
            ) : (
              <div className="mt-3 flex flex-col gap-3">
                {findings.map((f) => (
                  <FindingCard
                    key={f.id}
                    finding={f}
                    docs={docs}
                    active={f.id === activeId}
                    onActivate={setActiveId}
                  />
                ))}
              </div>
            )}
          </section>

          {detail.actions.length > 0 && (
            <section aria-labelledby="fix-title">
              <h2 id="fix-title" className="text-[18px] font-bold">
                Fix it
              </h2>
              <ul className="mt-3 divide-y rounded-lg border bg-sheet">
                {detail.actions.map((a) => (
                  <li key={a.id}>
                    <Link
                      to={`/months/${claim.month}/actions?a=${a.id}`}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-stamp-wash/60"
                    >
                      <span className="font-semibold">{a.title}</span>
                      <span className="text-[13.5px] text-graphite">
                        {a.status === 'draft' ? 'Letter drafted' : 'Task'}, due{' '}
                        {weekdayDate(a.due_date)}
                      </span>
                      <DueChip due={a.due_date} asOf={detail.as_of} className="ml-auto" />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="docs-title">
            <h2 id="docs-title" className="text-[18px] font-bold">
              Paperwork
            </h2>
            <ul className="mt-3 flex flex-wrap gap-2">
              {detail.documents.map((d) => (
                <li key={d.id}>
                  <Link
                    to={`/documents/${d.id}?claim=${encodeURIComponent(claim.id)}`}
                    className="flex items-center gap-2 rounded-md border bg-sheet px-3 py-2 text-[14px] hover:border-stamp"
                  >
                    <FileText className="size-4 text-graphite" aria-hidden />
                    <span className="font-semibold">{docTypeLabel(d)}</span>
                    <span className="text-graphite">{d.title}</span>
                  </Link>
                </li>
              ))}
              <li>
                <Link
                  to={`/patients/${patient.id}`}
                  className="flex items-center gap-2 rounded-md border bg-sheet px-3 py-2 text-[14px] hover:border-stamp"
                >
                  <CalendarDays className="size-4 text-graphite" aria-hidden />
                  <span className="font-semibold">Patient timeline</span>
                  <span className="text-graphite">{monthName(claim.month)}</span>
                </Link>
              </li>
            </ul>
          </section>
        </div>

        <LinesTable
          lines={claim.lines}
          labels={detail.code_labels}
          worst={worst}
          highlighted={highlighted}
          note={detail.tariff_note}
        />
      </div>
    </Page>
  )
}

function worstSeverityByLine(findings: Finding[]) {
  const worst = new Map<string, Severity>()
  for (const f of findings) {
    for (const id of f.claim_line_ids ?? []) {
      const prev = worst.get(id)
      if (!prev || SEVERITY_ORDER.indexOf(f.severity) < SEVERITY_ORDER.indexOf(prev)) {
        worst.set(id, f.severity)
      }
    }
  }
  return worst
}

function LinesTable({
  lines,
  labels,
  worst,
  highlighted,
  note,
}: {
  lines: ClaimLine[]
  labels: Record<string, string>
  worst: Map<string, Severity>
  highlighted: Set<string>
  note: string
}) {
  const flagged = lines.filter((l) => worst.has(l.id)).length
  const scroller = useRef<HTMLDivElement>(null)
  const first = lines.find((l) => highlighted.has(l.id))?.id
  const firstFlagged = lines.find((l) => worst.has(l.id))?.id

  const scrollTo = (lineId: string | undefined, behavior: ScrollBehavior) => {
    const box = scroller.current
    const row = lineId && box?.querySelector<HTMLElement>(`[data-line="${CSS.escape(lineId)}"]`)
    if (!box || !row) return
    const head = box.querySelector('thead')?.offsetHeight ?? 0
    box.scrollTo({ top: row.offsetTop - head - 8, behavior })
  }

  // The table opens on the first flagged line; pointing at a finding brings its lines into
  // view. Both scroll the table only, never the page.
  useEffect(() => scrollTo(firstFlagged, 'instant'), [firstFlagged])
  useEffect(() => scrollTo(first, 'smooth'), [first])

  return (
    <section
      aria-labelledby="lines-title"
      className="flex max-h-[calc(100svh-7rem)] min-w-0 flex-col rounded-lg border bg-sheet lg:sticky lg:top-20"
    >
      <div className="flex items-baseline justify-between gap-4 border-b px-4 py-3">
        <h2 id="lines-title" className="text-[16px] font-bold">
          Claim lines
        </h2>
        <p className="text-[13px] text-graphite">
          {flagged > 0 ? `${plural(flagged, 'line')} flagged` : 'None flagged'}
        </p>
      </div>
      <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-[13.5px] tabular">
          <thead className="sticky top-0 z-10 bg-sheet text-left text-[12.5px] text-graphite shadow-[0_1px_0_var(--rule)]">
            <tr>
              <th scope="col" className="w-10 py-2 pl-3">
                <span className="sr-only">Status</span>
              </th>
              <th scope="col" className="py-2 pr-2 font-semibold">
                Date
              </th>
              <th scope="col" className="py-2 pr-2 font-semibold">
                Time
              </th>
              <th scope="col" className="py-2 pr-2 font-semibold">
                Service
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-semibold">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => {
              const severity = worst.get(line.id)
              const newDay = i === 0 || lines[i - 1].date !== line.date
              const lit = highlighted.has(line.id)
              return (
                <tr
                  key={line.id}
                  data-line={line.id}
                  className={cn(
                    newDay && i > 0 && 'border-t',
                    severity === 'block' && 'bg-blocked-wash/55',
                    severity === 'warn' && 'bg-fixable-wash/55',
                    lit && 'bg-stamp-wash! shadow-[inset_3px_0_0_var(--stamp)]',
                  )}
                >
                  <td className="py-1.5 pr-2 pl-3 align-top">
                    {severity && <SeverityMark severity={severity} />}
                  </td>
                  <td className="py-1.5 pr-2 align-top whitespace-nowrap">
                    {newDay ? weekdayDate(line.date) : ''}
                  </td>
                  <td className="py-1.5 pr-2 align-top text-graphite">{clock(line.time)}</td>
                  <td className="py-1.5 pr-2 align-top">
                    <span className="text-graphite">{line.code}</span>{' '}
                    <span lang="de" className="whitespace-nowrap">
                      {labels[line.code]}
                    </span>
                    {line.quantity > 1 && <span className="text-graphite"> ×{line.quantity}</span>}
                  </td>
                  <td className="py-1.5 pr-4 text-right align-top">{money(line.amount_cents)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t px-4 py-2.5 text-[12.5px] text-graphite">{note}</p>
    </section>
  )
}
