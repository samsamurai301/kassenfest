import { Info, ShieldCheck } from 'lucide-react'
import {
  type AuditStatus,
  type BoardCard,
  type ClaimStatus,
  type MonthBoard,
  useBoard,
} from '@/api/client'
import { RuleId } from '@/components/finding'
import { LoadError, Loading, Page } from '@/components/shell'
import { STATUS, StatusBadge } from '@/components/status'
import { domainShort, money, monthName, plural, weekdayDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const FILTERS: (ClaimStatus | 'all')[] = ['all', 'red', 'orange', 'green']

export function BoardScreen({ month, filter }: { month: string; filter: string | null }) {
  const board = useBoard(month)
  if (board.isPending) return <Loading what="the bills" />
  if (board.isError) return <LoadError error={board.error} />

  const active = FILTERS.find((f) => f === filter) ?? 'all'
  const cards = board.data.cards.filter((c) => active === 'all' || c.status === active)
  return (
    <Page>
      <Summary board={board.data} />
      <StatusFilter board={board.data} month={month} active={active} />
      {cards.length === 0 ? (
        <p className="mt-8 text-graphite">No bills with this status this month.</p>
      ) : (
        <ul className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map((card) => (
            <li key={card.claim_id}>
              <BillCard card={card} />
            </li>
          ))}
        </ul>
      )}
    </Page>
  )
}

function Summary({ board }: { board: MonthBoard }) {
  const count = (s: ClaimStatus) => board.by_status.find((b) => b.status === s)
  const patients = new Set(board.cards.map((c) => c.patient_id)).size
  const safe = board.total_cents - board.at_risk_cents
  const segments = [
    ...(['red', 'orange'] as const).map((s) => ({
      key: s,
      cents: count(s)?.at_risk_cents ?? 0,
      label: s === 'red' ? 'blocked' : 'fixable',
      tone: STATUS[s],
    })),
    { key: 'safe', cents: safe, label: 'safe to send', tone: STATUS.green },
  ]
  return (
    <section aria-labelledby="board-title">
      <p className="text-[14px] text-graphite">
        {monthName(board.month)} bills, checked {weekdayDate(board.as_of)}
      </p>
      <h1
        id="board-title"
        className="mt-1 max-w-[30ch] text-[32px] leading-[1.15] font-bold tracking-[-0.015em] text-balance sm:text-[38px]"
      >
        <span className="text-blocked">{money(board.at_risk_cents)}</span> of{' '}
        {money(board.total_cents)} would have been cut by the Kassen.
      </h1>
      <p className="mt-3 max-w-[70ch] text-[15.5px] text-graphite">
        {plural(board.cards.length, 'bill')} for {plural(patients, 'patient')}.{' '}
        {count('red')?.count} blocked, {count('orange')?.count} fixable before sending,{' '}
        {count('green')?.count} ready.
      </p>

      <div className="mt-6 max-w-[760px]">
        <div
          className="flex h-3 overflow-hidden rounded-full bg-rule"
          role="img"
          aria-label={segments.map((s) => `${money(s.cents)} ${s.label}`).join(', ')}
        >
          {segments.map((s) => (
            <div
              key={s.key}
              className={cn('h-full border-r-2 border-paper last:border-r-0', s.tone.fill)}
              style={{ width: `${(s.cents / board.total_cents) * 100}%` }}
            />
          ))}
        </div>
        <ul className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1 text-[13.5px]">
          {segments.map((s) => {
            const Icon = s.tone.icon
            return (
              <li key={s.key} className="flex items-center gap-1.5">
                <Icon className={cn('size-[15px]', s.tone.text)} strokeWidth={2.25} aria-hidden />
                <span className="font-semibold">{money(s.cents)}</span>
                <span className="text-graphite">{s.label}</span>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

function StatusFilter({
  board,
  month,
  active,
}: {
  board: MonthBoard
  month: string
  active: ClaimStatus | 'all'
}) {
  return (
    <nav
      aria-label="Filter by status"
      className="mt-9 flex flex-wrap items-center gap-2 border-b pb-4"
    >
      {FILTERS.map((f) => {
        const group = board.by_status.find((b) => b.status === f)
        const n = f === 'all' ? board.cards.length : (group?.count ?? 0)
        const tone = f === 'all' ? null : STATUS[f]
        const Icon = tone?.icon
        return (
          <Link
            key={f}
            to={f === 'all' ? `/months/${month}` : `/months/${month}?status=${f}`}
            replace
            aria-current={active === f ? 'true' : undefined}
            className={cn(
              'inline-flex h-9 items-center gap-2 rounded-full border bg-sheet px-3.5 text-[14px] font-semibold transition-colors hover:border-rule-strong',
              'aria-[current=true]:border-ink aria-[current=true]:bg-ink aria-[current=true]:text-white',
            )}
          >
            {Icon && <Icon className="size-4" strokeWidth={2.25} aria-hidden />}
            {tone ? tone.label : 'All bills'}
            <span className="font-normal tabular opacity-75">{n}</span>
          </Link>
        )
      })}
    </nav>
  )
}

function BillCard({ card }: { card: BoardCard }) {
  const tone = STATUS[card.status]
  const finding = card.top_finding
  const more = card.finding_count - 1
  const risky = card.at_risk_cents > 0
  return (
    <Link
      to={`/claims/${encodeURIComponent(card.claim_id)}`}
      className={cn(
        'group flex h-full flex-col rounded-lg border border-l-[5px] bg-sheet p-4 transition-[border-color,box-shadow] hover:border-rule-strong hover:shadow-[0_2px_10px_-4px_rgb(28_34_54/0.18)]',
        tone.edge,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-[17px] leading-tight font-bold group-hover:underline group-hover:decoration-stamp group-hover:underline-offset-4">
            {card.patient_name}
          </h2>
          <p className="mt-1 text-[13.5px] text-graphite">
            {card.payer.name}, {domainShort[card.domain]}
          </p>
        </div>
        <StatusBadge status={card.status} />
      </div>

      <p className="mt-4 flex items-baseline gap-2">
        <span className={cn('text-[22px] font-bold', risky ? tone.text : 'text-ink')}>
          {money(risky ? card.at_risk_cents : card.total_cents)}
        </span>
        <span className="text-[13.5px] text-graphite">
          {risky ? `at risk of ${money(card.total_cents)}` : `${plural(card.line_count, 'line')}`}
        </span>
      </p>

      {finding && (
        <div className="mt-3 border-t pt-3">
          {finding.severity === 'info' ? (
            <p className="flex gap-2 text-[13.5px] text-graphite">
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="line-clamp-2">{finding.message_en}</span>
            </p>
          ) : (
            <>
              <RuleId finding={finding} />
              <p className="mt-0.5 line-clamp-2 text-[14px] leading-snug text-ink">
                {finding.message_en}
              </p>
            </>
          )}
          {more > 0 && (
            <p className="mt-1.5 text-[13px] font-semibold text-graphite">
              and {plural(more, 'more finding')}
            </p>
          )}
        </div>
      )}

      {!finding && auditLine(card.audit) && (
        <p className="mt-3 flex items-center gap-1.5 border-t pt-3 text-[13.5px] text-graphite">
          <ShieldCheck className="size-4 shrink-0 text-stamp" aria-hidden />
          {auditLine(card.audit)}
        </p>
      )}
    </Link>
  )
}

function auditLine(audit: AuditStatus) {
  const objections = audit.dismissed + audit.noted
  switch (audit.state) {
    case 'done':
      return objections === 0
        ? 'The Kasse\u2019s auditor found nothing to object to'
        : `Survived the auditor: ${plural(objections, 'objection')} answered`
    case 'running':
      return 'The Kasse\u2019s auditor is checking it…'
    case 'pending':
      return 'Not attacked by the auditor yet'
    case 'error':
      return 'The auditor\u2019s last attack failed'
    default:
      return null
  }
}
