import { useQueryClient } from '@tanstack/react-query'
import {
  CircleCheck,
  Info,
  LoaderCircle,
  type LucideIcon,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useRef } from 'react'
import {
  type ClaimAudit,
  type ClaimLine,
  type DocumentInfo,
  type Evidence,
  type ObjectionVerdict,
  useStartAudit,
} from '@/api/client'
import { EvidenceThumb } from '@/components/finding'
import { dateTime, plural, weekdayDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { DOC_TYPE } from '@/screens/claim'

type Verdict = ObjectionVerdict['verdict']

const VERDICT: Record<Verdict, { label: string; icon: LucideIcon; tone: string; stroke: string }> =
  {
    dismissed: {
      label: 'Dismissed',
      icon: CircleCheck,
      tone: 'bg-ready-wash text-ready',
      stroke: 'var(--ready-edge)',
    },
    upheld: {
      label: 'Upheld',
      icon: TriangleAlert,
      tone: 'bg-fixable-wash text-fixable',
      stroke: 'var(--fixable-edge)',
    },
    noted: { label: 'Noted', icon: Info, tone: 'bg-muted text-graphite', stroke: 'var(--graphite)' },
  }

const CODE_KIND = {
  FACT: 'A field on a page',
  INFO: 'A suspicion, never a rejection',
} as const

/**
 * The Kasse's auditor against a clean bill: what it objected, round by round, and what the
 * resolver found when it checked each point. Pointing at an objection lights up its lines.
 */
export function AuditPanel({
  claimId,
  audit,
  lines,
  docs,
  onLines,
}: {
  claimId: string
  audit: ClaimAudit
  lines: ClaimLine[]
  docs: Record<string, DocumentInfo>
  onLines: (ids: string[] | null) => void
}) {
  const queryClient = useQueryClient()
  const previous = useRef(audit.state)
  useEffect(() => {
    // Verdicts in: an upheld objection changes the bill's status on the board too.
    if (previous.current === 'running' && audit.state !== 'running') {
      void queryClient.invalidateQueries({ queryKey: ['board'] })
    }
    previous.current = audit.state
  }, [audit.state, queryClient])

  if (audit.state === 'not_needed' || audit.state === 'unavailable') return null
  const verdicts = audit.rounds.flatMap((r) => r.verdicts)
  const Shield = audit.upheld > 0 ? ShieldAlert : ShieldCheck

  return (
    <section aria-labelledby="audit-title">
      <h2 id="audit-title" className="flex items-center gap-2 text-[18px] font-bold">
        <Shield
          className={cn('size-5', audit.upheld > 0 ? 'text-fixable' : 'text-stamp')}
          aria-hidden
        />
        The Kasse&rsquo;s auditor
      </h2>
      <p className="mt-1.5 max-w-[68ch] text-[14px] leading-snug text-graphite">
        A second Muse Spark agent plays the Kasse&rsquo;s Prüfer and tries to reject every bill the
        rules pass. It may object only with the Kasse&rsquo;s rejection codes, a field on a page, or
        a suspicion. The resolver then checks each point against the rules, the records and the
        paperwork, without a model.
      </p>

      {audit.state === 'done' && (
        <>
          <Outcome audit={audit} objections={verdicts.length} />
          {audit.rounds.map((round) => (
            <div key={round.round} className="mt-4">
              <h3 className="text-[13px] font-bold tracking-[0.04em] text-graphite uppercase">
                Round {round.round}
              </h3>
              <ol className="mt-2 flex flex-col gap-3">
                {round.verdicts.map((v, i) => (
                  <Exchange
                    key={i}
                    verdict={v}
                    claimId={claimId}
                    label={audit.code_labels?.[v.objection.code]}
                    lines={lines}
                    docs={docs}
                    onLines={onLines}
                  />
                ))}
              </ol>
            </div>
          ))}
          {audit.rounds.length === 1 && (
            <p className="mt-4 text-[13.5px] text-graphite">
              <span className="font-semibold text-ink">Round 2:</span> shown these answers, the
              auditor raised nothing new.
            </p>
          )}
          <p className="mt-4 text-[12.5px] text-graphite">
            {audit.model}, reasoning high
            {audit.created_at && <>, {dateTime(audit.created_at)}</>}
            {(audit.repeats ?? 0) > 0 && <>; {plural(audit.repeats ?? 0, 'repeated point')} dropped</>}
          </p>
        </>
      )}

      {audit.state === 'running' && (
        <p className="mt-4 flex items-center gap-2.5 rounded-lg border bg-sheet px-4 py-3 text-[14px] font-semibold">
          <LoaderCircle className="size-4 animate-spin text-stamp" aria-hidden />
          The auditor is reading the bill and the paperwork…
        </p>
      )}

      {(audit.state === 'pending' || audit.state === 'error') && (
        <StartAudit claimId={claimId} error={audit.state === 'error' ? audit.error : null} />
      )}
    </section>
  )
}

function Outcome({ audit, objections }: { audit: ClaimAudit; objections: number }) {
  const text =
    objections === 0
      ? 'The auditor found nothing to object to.'
      : audit.upheld > 0
        ? `The auditor found ${plural(audit.upheld, 'point')} the rules missed: a human should look before this bill goes out.`
        : `Survived the auditor: ${plural(audit.dismissed, 'objection')} dismissed` +
          (audit.noted ? `, ${plural(audit.noted, 'suspicion')} noted for a human.` : '.')
  return (
    <p
      className={cn(
        'mt-4 rounded-lg px-4 py-3 text-[15px] font-semibold',
        audit.upheld > 0 ? 'bg-fixable-wash text-fixable' : 'bg-ready-wash text-ready',
      )}
    >
      {text}
    </p>
  )
}

function scopeOf(ids: string[], lines: ClaimLine[]) {
  if (ids.length === 0) return 'Whole bill'
  const named = lines.filter((l) => ids.includes(l.id))
  const days = [...new Set(named.map((l) => l.date))]
  const shown = days.slice(0, 3).map(weekdayDate).join(', ')
  return `${shown}${days.length > 3 ? ` and ${days.length - 3} more days` : ''} (${plural(named.length, 'line')})`
}

function Exchange({
  verdict: v,
  claimId,
  label,
  lines,
  docs,
  onLines,
}: {
  verdict: ObjectionVerdict
  claimId: string
  label: string | undefined
  lines: ClaimLine[]
  docs: Record<string, DocumentInfo>
  onLines: (ids: string[] | null) => void
}) {
  const o = v.objection
  const tone = VERDICT[v.verdict]
  const Icon = tone.icon
  const cited = o.document_id ? docs[o.document_id] : undefined
  const evidence = (v.evidence ?? []).filter((ev) => docs[ev.document_id])
  const kind = o.code === 'FACT' || o.code === 'INFO' ? CODE_KIND[o.code] : label
  return (
    <li
      className="rounded-lg border bg-sheet"
      onMouseEnter={() => onLines(o.claim_line_ids)}
      onMouseLeave={() => onLines(null)}
    >
      <div className="p-4">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="text-[12px] font-bold tracking-[0.04em] text-graphite uppercase">
            Auditor
          </span>
          <span className="rounded bg-ink px-1.5 py-px text-[12.5px] font-bold text-white tabular">
            {o.code}
          </span>
          {kind && <span className="text-[13.5px] font-semibold">{kind}</span>}
          <span className="ml-auto text-[13px] text-graphite">{scopeOf(o.claim_line_ids, lines)}</span>
        </div>
        <p className="mt-2 text-[15px] leading-snug font-semibold" lang="en">
          {o.statement_en}
        </p>
        <p className="mt-1 text-[14px] leading-snug text-graphite" lang="de">
          <abbr title="Deutsch" className="mr-1.5 text-[11px] font-bold no-underline">
            DE
          </abbr>
          {o.statement}
        </p>
        {o.code === 'FACT' && cited && (
          <p className="mt-1.5 text-[13px] text-graphite">
            Cites the {DOC_TYPE[cited.doc_type]}, field{' '}
            <code className="font-semibold text-ink">{o.field_path}</code>
            {o.reads !== null && o.reads !== undefined && (
              <>
                , which it reads as{' '}
                <span className="font-semibold text-ink">“{o.reads || 'blank'}”</span>
              </>
            )}
          </p>
        )}
      </div>
      <div className="rounded-b-lg border-t bg-paper px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[12px] font-bold tracking-[0.04em] text-graphite uppercase">
            Resolver
          </span>
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-2 text-[13px] leading-5 font-semibold',
              tone.tone,
            )}
          >
            <Icon className="size-[15px]" strokeWidth={2.25} aria-hidden />
            {tone.label}
          </span>
        </div>
        <p className="mt-2 text-[14px] leading-snug text-ink">{v.reason}</p>
        {(v.checked?.length ?? 0) > 0 && (
          <p className="mt-1.5 text-[12.5px] text-graphite">
            Checked: <span className="font-semibold">{v.checked?.join(' · ')}</span>
          </p>
        )}
        {evidence.length > 0 && (
          <div className="mt-3 flex gap-3 overflow-x-auto pb-1">
            {evidence.map((ev, i) => (
              <EvidenceThumb
                key={i}
                ev={ev}
                doc={docs[ev.document_id]}
                href={fieldHref(ev, claimId)}
                stroke={tone.stroke}
              />
            ))}
          </div>
        )}
      </div>
    </li>
  )
}

function fieldHref(ev: Evidence, claimId: string) {
  const params = new URLSearchParams({ page: String(ev.page ?? 0), claim: claimId })
  if (ev.field_path) params.set('field', ev.field_path)
  return `/documents/${encodeURIComponent(ev.document_id)}?${params}`
}

function StartAudit({ claimId, error }: { claimId: string; error: string | null | undefined }) {
  const start = useStartAudit(claimId)
  return (
    <div className="mt-4 rounded-lg border bg-sheet px-4 py-3">
      <p className="text-[14px]">
        {error
          ? `The last attack failed: ${error}`
          : 'Not attacked yet in its current state: the auditor runs after every upload.'}
      </p>
      <button
        type="button"
        disabled={start.isPending}
        onClick={() => start.mutate()}
        className="mt-3 inline-flex h-9 items-center gap-2 rounded-full border bg-sheet px-3.5 text-[14px] font-semibold transition-colors hover:border-rule-strong disabled:opacity-50"
      >
        <ShieldCheck className="size-4 text-stamp" aria-hidden />
        {error ? 'Try again' : 'Let the auditor attack this bill'}
      </button>
      {start.isError && <p className="mt-2 text-[13.5px] text-blocked">{start.error.message}</p>}
    </div>
  )
}
