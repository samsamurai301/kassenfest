import { CircleCheck, Info, type LucideIcon, OctagonX, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ClaimStatus, Severity } from '@/api/client'

// Every status is a word + an icon shape + a colour, so it reads in greyscale too.
type Tone = {
  label: string
  icon: LucideIcon
  text: string
  wash: string
  edge: string
  fill: string
}

export const STATUS: Record<ClaimStatus, Tone & { hint: string }> = {
  red: {
    label: 'Blocked',
    hint: 'Will be rejected as is',
    icon: OctagonX,
    text: 'text-blocked',
    wash: 'bg-blocked-wash',
    edge: 'border-l-blocked-edge',
    fill: 'bg-blocked-edge',
  },
  orange: {
    label: 'Fixable',
    hint: 'Fix or check before sending',
    icon: TriangleAlert,
    text: 'text-fixable',
    wash: 'bg-fixable-wash',
    edge: 'border-l-fixable-edge',
    fill: 'bg-fixable-edge',
  },
  green: {
    label: 'Ready',
    hint: 'Ready to send',
    icon: CircleCheck,
    text: 'text-ready',
    wash: 'bg-ready-wash',
    edge: 'border-l-ready-edge',
    fill: 'bg-ready-edge',
  },
}

export const SEVERITY: Record<Severity, Tone & { stroke: string }> = {
  block: { ...STATUS.red, label: 'Blocks', stroke: 'var(--blocked-edge)' },
  warn: { ...STATUS.orange, label: 'Warning', stroke: 'var(--fixable-edge)' },
  info: {
    label: 'Note',
    icon: Info,
    text: 'text-graphite',
    wash: 'bg-muted',
    edge: 'border-l-rule-strong',
    fill: 'bg-rule-strong',
    stroke: 'var(--graphite)',
  },
}

export const SEVERITY_ORDER: Severity[] = ['block', 'warn', 'info']

function Pill({ tone, label, className }: { tone: Tone; label?: string; className?: string }) {
  const Icon = tone.icon
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-2 text-[13px] leading-5 font-semibold',
        tone.wash,
        tone.text,
        className,
      )}
    >
      <Icon className="size-[15px]" strokeWidth={2.25} aria-hidden />
      {label ?? tone.label}
    </span>
  )
}

export function StatusBadge({ status, className }: { status: ClaimStatus; className?: string }) {
  return <Pill tone={STATUS[status]} className={className} />
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return <Pill tone={SEVERITY[severity]} className={className} />
}

/** Icon only, for dense rows; the word goes to screen readers. */
export function SeverityMark({ severity, className }: { severity: Severity; className?: string }) {
  const tone = SEVERITY[severity]
  const Icon = tone.icon
  return (
    <span className={cn('inline-flex', tone.text, className)} title={tone.label}>
      <Icon className="size-4" strokeWidth={2.25} aria-hidden />
      <span className="sr-only">{tone.label}</span>
    </span>
  )
}
