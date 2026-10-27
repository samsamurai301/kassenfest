import { Clock } from 'lucide-react'
import type { ReactNode } from 'react'
import type { DocumentInfo, Evidence, Finding, PixelBox } from '@/api/client'
import { pageImageUrl } from '@/api/client'
import { SEVERITY, SeverityBadge } from '@/components/status'
import { daysBetween, money, plural, weekdayDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const THUMB_W = 188
const THUMB_H = 112

/** viewBox around a box, padded and widened to the thumbnail's aspect, kept on the page. */
export function cropViewBox(
  box: PixelBox,
  page: { width: number; height: number },
  aspect = THUMB_W / THUMB_H,
  pad = 36,
): [number, number, number, number] {
  let x = box[0] - pad
  let y = box[1] - pad
  let w = box[2] - box[0] + pad * 2
  let h = box[3] - box[1] + pad * 2
  if (w / h > aspect) {
    y -= (w / aspect - h) / 2
    h = w / aspect
  } else {
    x -= (h * aspect - w) / 2
    w = h * aspect
  }
  w = Math.min(w, page.width)
  h = Math.min(h, page.height)
  x = Math.min(Math.max(x, 0), page.width - w)
  y = Math.min(Math.max(y, 0), page.height - h)
  return [x, y, w, h]
}

export function evidenceHref(ev: Evidence, finding: Finding) {
  const params = new URLSearchParams({ page: String(ev.page ?? 0), finding: finding.id })
  if (finding.claim_id) params.set('claim', finding.claim_id)
  return `/documents/${encodeURIComponent(ev.document_id)}?${params}`
}

export function EvidenceThumb({
  ev,
  finding,
  doc,
}: {
  ev: Evidence
  finding: Finding
  doc: DocumentInfo
}) {
  const page = doc.pages[ev.page ?? 0]
  if (!ev.box || !page) return null
  const box = ev.box as PixelBox
  const [x, y, w, h] = cropViewBox(box, page)
  const stroke = SEVERITY[finding.severity].stroke
  return (
    <Link
      to={evidenceHref(ev, finding)}
      className="group/thumb block w-[188px] shrink-0 rounded-md focus-visible:outline-offset-4"
      title={`Open ${doc.title}`}
    >
      <svg
        viewBox={`${x} ${y} ${w} ${h}`}
        width={THUMB_W}
        height={THUMB_H}
        className="block rounded-md border bg-white transition-[border-color] group-hover/thumb:border-stamp"
        role="img"
        aria-label={`Evidence on ${doc.title}: ${ev.note ?? ev.field_path ?? ''}`}
      >
        <image
          href={pageImageUrl(ev.document_id, ev.page ?? 0)}
          width={page.width}
          height={page.height}
        />
        <rect
          x={box[0]}
          y={box[1]}
          width={box[2] - box[0]}
          height={box[3] - box[1]}
          rx={3}
          fill={stroke}
          fillOpacity={0.1}
          stroke={stroke}
          strokeWidth={2.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="mt-1.5 block truncate text-[12.5px] text-graphite group-hover/thumb:text-stamp">
        {ev.note ?? doc.title}
      </span>
    </Link>
  )
}

export function RuleId({ finding }: { finding: Finding }) {
  return (
    <span className="text-[13px] font-bold tracking-[0.01em] text-ink">
      {finding.rule_id}
      <span className="ml-1 font-normal text-graphite">v{finding.rule_version}</span>
    </span>
  )
}

/**
 * One finding: rule, both languages, legal source, money, evidence. Hover and focus report
 * back through `onActivate`, so the claim lines or page boxes it refers to can light up.
 */
export function FindingCard({
  finding,
  docs,
  active = false,
  onActivate,
  showEvidence = true,
  footer,
  className,
}: {
  finding: Finding
  docs?: Record<string, DocumentInfo>
  active?: boolean
  onActivate?: (id: string | null) => void
  showEvidence?: boolean
  footer?: ReactNode
  className?: string
}) {
  const lines = finding.claim_line_ids?.length ?? 0
  const evidence = (finding.evidence ?? []).filter((ev) => docs?.[ev.document_id])
  return (
    <article
      className={cn(
        'rounded-lg border border-l-4 bg-sheet p-4 transition-shadow',
        SEVERITY[finding.severity].edge,
        active && 'shadow-[0_0_0_2px_var(--stamp)]',
        className,
      )}
      onMouseEnter={() => onActivate?.(finding.id)}
      onMouseLeave={() => onActivate?.(null)}
      onFocus={() => onActivate?.(finding.id)}
      aria-label={`${SEVERITY[finding.severity].label}: ${finding.rule_id}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <SeverityBadge severity={finding.severity} />
        <RuleId finding={finding} />
        {(finding.amount_at_risk_cents ?? 0) > 0 && (
          <span className="ml-auto text-[14px] font-bold tabular">
            {money(finding.amount_at_risk_cents ?? 0)}
            <span className="font-normal text-graphite"> at risk</span>
          </span>
        )}
      </div>
      <p className="mt-2.5 text-[15px] leading-snug font-semibold text-ink" lang="en">
        {finding.message_en}
      </p>
      <p className="mt-1.5 text-[14px] leading-snug text-graphite" lang="de">
        <abbr title="Deutsch" className="mr-1.5 text-[11px] font-bold text-graphite no-underline">
          DE
        </abbr>
        {finding.message_de}
      </p>
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
        <div className="flex gap-1.5">
          <dt className="text-graphite">Source</dt>
          <dd className="font-semibold">{finding.sources.join('; ')}</dd>
        </div>
        {(finding.kasse_codes?.length ?? 0) > 0 && (
          <div className="flex gap-1.5">
            <dt className="text-graphite">Kasse codes</dt>
            <dd className="font-semibold tabular">{finding.kasse_codes?.join(', ')}</dd>
          </div>
        )}
        {lines > 0 && (
          <div className="flex gap-1.5">
            <dt className="text-graphite">Affects</dt>
            <dd className="font-semibold">{plural(lines, 'line')}</dd>
          </div>
        )}
      </dl>
      {showEvidence && evidence.length > 0 && docs && (
        <div className="mt-4 flex gap-3 overflow-x-auto pb-1">
          {evidence.map((ev, i) => (
            <EvidenceThumb key={i} ev={ev} finding={finding} doc={docs[ev.document_id]} />
          ))}
        </div>
      )}
      {footer}
    </article>
  )
}

export function DueChip({
  due,
  asOf,
  className,
}: {
  due: string
  asOf: string
  className?: string
}) {
  const days = daysBetween(asOf, due)
  const label =
    days < 0
      ? `Overdue by ${plural(-days, 'day')}`
      : days === 0
        ? 'Due today'
        : days === 1
          ? 'Due tomorrow'
          : `${days} days left`
  const tone =
    days < 0
      ? 'bg-blocked-wash text-blocked'
      : days <= 3
        ? 'bg-fixable-wash text-fixable'
        : 'bg-muted text-ink'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-2 text-[13px] leading-5 font-semibold tabular',
        tone,
        className,
      )}
      title={`Due ${weekdayDate(due)}`}
    >
      <Clock className="size-[15px]" strokeWidth={2.25} aria-hidden />
      {label}
    </span>
  )
}
