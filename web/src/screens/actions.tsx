import {
  Check,
  CircleAlert,
  Copy,
  LoaderCircle,
  MessageSquare,
  PenLine,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import {
  type Action,
  type ActionList,
  type FixerStatus,
  type FixRun,
  type FixStep,
  useActions,
  useDraftActions,
  useFixRun,
} from '@/api/client'
import { DueChip } from '@/components/finding'
import { LoadError, Loading, Page } from '@/components/shell'
import { Button } from '@/components/ui/button'
import { dateTime, daysBetween, money, monthName, plural, weekdayDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const KIND: Record<Action['kind'], string> = {
  folgeverordnung_request: 'Folgeverordnung request',
  stamp_request: 'Stamp request',
  prescription_change: 'Prescription change',
  signature_request: 'Signature request',
  kasse_letter: 'Letter to the Kasse',
  eigenanteil_notice: 'Cost information',
  claim_correction: 'Bill correction',
  staff_followup: 'Note to staff',
}

const CHANNEL: Record<Action['letter']['channel'], string> = {
  fax: 'Fax',
  post: 'Letter by post',
  handover: 'Handed over at the next visit',
  internal: 'Internal note',
}

export function ActionsScreen({ month, selected }: { month: string; selected: string | null }) {
  const actions = useActions(month)
  if (actions.isPending) return <Loading what="the actions" />
  if (actions.isError) return <LoadError error={actions.error} />
  return <ActionsView list={actions.data} selected={selected} />
}

function ActionsView({ list, selected }: { list: ActionList; selected: string | null }) {
  const current = list.actions.find((a) => a.id === selected) ?? list.actions[0]
  const overdue = list.actions.filter((a) => daysBetween(list.as_of, a.due_date) < 0).length
  const soon = list.actions.filter((a) => {
    const days = daysBetween(list.as_of, a.due_date)
    return days >= 0 && days <= 3
  }).length
  return (
    <Page>
      <p className="text-[14px] text-graphite">
        {monthName(list.month)} bills, today is {weekdayDate(list.as_of)}
      </p>
      <h1 className="mt-1 text-[30px] leading-tight font-bold tracking-[-0.015em]">
        Actions & deadlines
      </h1>
      <p className="mt-2 max-w-[70ch] text-[15.5px] text-graphite">
        {plural(list.actions.length, 'thing')} to do before the bills go out: {overdue} overdue,{' '}
        {soon} due in the next 3 days. Kassenfest drafts the letters; you check and send them.
      </p>
      <FixerBanner month={list.month} fixer={list.fixer} />

      {current && (
        <div className="mt-7 grid items-start gap-6 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
          <ol className="flex flex-col gap-2.5" aria-label="Actions by due date">
            {list.actions.map((a) => (
              <li key={a.id}>
                <Link
                  to={`/months/${list.month}/actions?a=${a.id}`}
                  replace
                  aria-current={a.id === current.id ? 'true' : undefined}
                  className={cn(
                    'block rounded-lg border bg-sheet p-4 transition-[border-color,box-shadow] hover:border-rule-strong',
                    'aria-[current=true]:border-stamp aria-[current=true]:shadow-[0_0_0_1px_var(--stamp)]',
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <DueChip due={a.due_date} asOf={list.as_of} />
                    <span className="text-[13px] text-graphite">{KIND[a.kind]}</span>
                  </div>
                  <p className="mt-2 leading-snug font-semibold">{a.title}</p>
                  <p className="mt-1 text-[13.5px] text-graphite">
                    {a.patient_name}, due {weekdayDate(a.due_date)}
                    {a.amount_cents > 0 && (
                      <>
                        ,{' '}
                        <span className="font-semibold text-ink tabular">
                          {money(a.amount_cents)}
                        </span>{' '}
                        on the line
                      </>
                    )}
                  </p>
                </Link>
              </li>
            ))}
          </ol>

          <Draft key={current.id} action={current} list={list} />
        </div>
      )}
    </Page>
  )
}

/** Where the actions come from in the pipeline world: the fixer agent, and whether it is done. */
function FixerBanner({ month, fixer }: { month: string; fixer: FixerStatus }) {
  const draft = useDraftActions(month)
  if (fixer.state === 'unavailable') return null
  if (fixer.state === 'running') {
    return (
      <p className="mt-5 flex max-w-[70ch] items-center gap-2.5 rounded-lg border bg-sheet px-4 py-3 text-[14px] font-semibold">
        <LoaderCircle className="size-4 shrink-0 animate-spin text-stamp" aria-hidden />
        The fixer agent is drafting for {fixer.running.join(', ')}…
      </p>
    )
  }
  if (fixer.state === 'pending') {
    return (
      <div className="mt-5 max-w-[70ch] rounded-lg border bg-sheet px-4 py-3">
        <p className="text-[14px]">
          {plural(fixer.due.length, 'patient')} with findings that have no drafted actions yet:{' '}
          {fixer.due.join(', ')}.
        </p>
        <button
          type="button"
          disabled={draft.isPending}
          onClick={() => draft.mutate()}
          className="mt-3 inline-flex h-9 items-center gap-2 rounded-full border bg-sheet px-3.5 text-[14px] font-semibold transition-colors hover:border-rule-strong disabled:opacity-50"
        >
          <PenLine className="size-4 text-stamp" aria-hidden />
          Draft the actions
        </button>
        {draft.isError && <p className="mt-2 text-[13.5px] text-blocked">{draft.error.message}</p>}
      </div>
    )
  }
  return (
    <p className="mt-3 max-w-[70ch] text-[13.5px] text-graphite">
      Drafted by the fixer agent ({fixer.model ?? 'Muse Spark'}) from the findings of{' '}
      {plural(fixer.drafted, 'patient')}, with tools only: due dates from the working-day calendar,
      and every date, amount and number in a letter checked against the records.
    </p>
  )
}

function Draft({ action, list }: { action: Action; list: ActionList }) {
  const [copied, setCopied] = useState(false)
  const { letter } = action
  const { provider } = list
  const text = [...letter.recipient, '', letter.subject, '', letter.body].join('\n')
  const letterhead = [provider.name, ...provider.address].join(', ')

  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <section
      aria-labelledby="draft-title"
      className="min-w-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-2 lg:pb-6"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id="draft-title" className="text-[18px] font-bold">
          {action.status === 'draft' ? 'Drafted letter' : 'Task note'}
        </h2>
        <span className="text-[14px] text-graphite">{CHANNEL[letter.channel]}</span>
        <div className="ml-auto flex items-center gap-2">
          {action.claim_id && (
            <Link
              to={`/claims/${encodeURIComponent(action.claim_id)}`}
              className="rounded px-1 text-[14px] font-semibold text-stamp hover:underline"
            >
              Open the bill
            </Link>
          )}
          <Button variant="outline" onClick={copy} aria-live="polite">
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? 'Copied' : 'Copy text'}
          </Button>
        </div>
      </div>
      <p className="mt-1 max-w-[70ch] text-[14px] text-graphite">{action.why}</p>

      <article
        className="relative mt-4 max-w-[720px] overflow-hidden rounded-sm border bg-white px-8 py-9 shadow-[0_1px_2px_rgb(28_34_54/0.06),0_8px_24px_-12px_rgb(28_34_54/0.18)] sm:px-14 sm:py-12"
        lang="de"
      >
        <DraftStamp />
        <p className="font-sans text-[11.5px] text-graphite">{letterhead}</p>
        <address className="mt-3 font-serif text-[16px] leading-[1.45] not-italic">
          {letter.recipient.map((line) => (
            <span key={line} className="block">
              {line}
            </span>
          ))}
        </address>
        <p className="mt-8 text-right font-serif text-[15px]">
          {provider.municipality}, {list.as_of.split('-').reverse().join('.')}
        </p>
        <p className="mt-6 font-serif text-[16.5px] leading-snug font-semibold">{letter.subject}</p>
        <div className="mt-5 font-serif text-[16px] leading-[1.65] whitespace-pre-line">
          {letter.body}
        </div>
      </article>

      {action.run_id && <Trace runId={action.run_id} actionId={action.id} />}
    </section>
  )
}

/** "ENTWURF" in practice-stamp violet: this is a draft, nothing has been sent. */
function DraftStamp() {
  return (
    <span
      className="pointer-events-none absolute top-7 right-6 rotate-[-7deg] rounded-[3px] border-[2.5px] border-stamp/70 px-2.5 py-0.5 font-sans text-[15px] font-extrabold tracking-[0.12em] text-stamp/75 sm:right-10"
      aria-label="Draft, not sent"
    >
      ENTWURF
    </span>
  )
}

// --- the agent's trace ----------------------------------------------------------------------

type Args = Record<string, unknown>
type Result = Record<string, unknown>

const str = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : JSON.stringify(v))

/** The steps of the run that made this action: its create_action, the draft and the deadline it
 * names, and earlier drafts to the same recipient that were sent back. */
function stepsOf(run: FixRun, actionId: string): Set<number> {
  const n = run.actions.indexOf(actionId) + 1
  const steps = run.steps
  const create = steps.findIndex(
    (s) => s.tool === 'create_action' && (s.result as Result | null)?.action === `X${n}`,
  )
  const mine = new Set<number>()
  if (create < 0) return mine
  mine.add(create)
  const args = (steps[create].args ?? {}) as Args
  const draft = steps.findIndex(
    (s) => s.tool === 'draft_letter' && (s.result as Result | null)?.letter === args.letter,
  )
  if (draft >= 0) {
    mine.add(draft)
    const to = (steps[draft].args as Args | null)?.recipient
    steps.forEach((s, i) => {
      if (i < draft && s.tool === 'draft_letter' && !s.ok && (s.args as Args)?.recipient === to)
        mine.add(i)
    })
  }
  steps.forEach((s, i) => {
    if (s.tool === 'compute_deadline' && (s.result as Result | null)?.deadline === args.deadline)
      mine.add(i)
    if (i < create && s.tool === 'create_action' && !s.ok) mine.add(i)
  })
  return mine
}

function describe(step: FixStep): { call: string; result: string } {
  const a = (step.args ?? {}) as Args
  const r = (step.result ?? {}) as Result
  if (!step.ok) {
    const problems = (r.problems as string[] | undefined) ?? []
    return { call: callText(step.tool ?? '', a), result: `Sent back: ${problems.join('; ')}` }
  }
  switch (step.tool) {
    case 'get_claim_findings': {
      const findings = (r.findings as Result[] | undefined) ?? []
      const listed = findings.map((f) => `${str(f.ref)} ${str(f.rule)} (${str(f.at_risk)})`)
      return { call: 'get_claim_findings()', result: listed.join(', ') || 'no findings' }
    }
    case 'get_patient_context': {
      const p = (r.patient ?? {}) as Result
      const count = (key: string, word: string) =>
        plural(((r[key] as unknown[] | undefined) ?? []).length, word)
      return {
        call: 'get_patient_context()',
        result: [
          str(p.name),
          count('doctors', 'doctor'),
          count('prescriptions', 'Verordnung'),
          count('approvals', 'Genehmigung'),
          count('stays', 'stay'),
        ].join(', '),
      }
    }
    case 'get_document':
      return { call: callText('get_document', a), result: str(r.type) }
    case 'compute_deadline':
      return {
        call: callText('compute_deadline', a),
        result: `${str(r.deadline)}: ${str(r.date)}, ${str(r.basis)}`,
      }
    case 'draft_letter':
      return {
        call: `draft_letter(to ${str(a.recipient)}: “${str(a.subject)}”)`,
        result: `${str(r.letter)} accepted, ${str(r.channel)} to ${((r.to as string[]) ?? []).join(', ')}`,
      }
    case 'create_action':
      return {
        call: `create_action(${str(a.kind)} for ${((a.findings as string[]) ?? []).join(', ')}, deadline ${str(a.deadline)}, letter ${str(a.letter)})`,
        result: `${str(r.action)} filed, due ${str(r.due)}, ${str(r.money_on_it)} on it`,
      }
  }
  return { call: callText(step.tool ?? '?', a), result: JSON.stringify(r) }
}

function callText(tool: string, a: Args) {
  const shown = Object.entries(a)
    .filter(([k]) => k !== 'body')
    .map(([k, v]) => `${k}: ${str(v)}`)
  return `${tool}(${shown.join(', ')})`
}

function Trace({ runId, actionId }: { runId: string; actionId: string }) {
  const run = useFixRun(runId)
  const [all, setAll] = useState(false)
  if (run.isPending)
    return <p className="mt-6 text-[13.5px] text-graphite">Loading how it was drafted…</p>
  if (run.isError) return null
  const r = run.data
  const mine = stepsOf(r, actionId)
  const calls = r.steps.filter((s) => s.kind === 'call')
  const turns = new Set(r.steps.map((s) => s.turn)).size
  const sentBack = calls.filter((s) => !s.ok).length
  const last = r.steps.length - 1
  const shown = r.steps
    .map((step, i) => ({ step, i }))
    .filter(({ step, i }) => all || mine.has(i) || step.kind !== 'call')
    .filter(({ step, i }) => !(i === last && step.kind === 'say' && step.text === r.note))

  return (
    <section aria-labelledby="trace-title" className="mt-8 max-w-[720px]">
      <h3 id="trace-title" className="text-[16px] font-bold">
        How the fixer agent drafted this
      </h3>
      <p className="mt-1 text-[13.5px] text-graphite">
        {plural(calls.length, 'tool call')} in {plural(turns, 'turn')} for {r.patient_name}
        {sentBack > 0 && <>, {plural(sentBack, 'call')} sent back by the checks</>}. {r.model},
        drafted for{' '}
        <span title={`Recorded ${dateTime(r.created_at)}`}>{weekdayDate(r.as_of)}</span>. The steps
        behind this action are marked.
      </p>
      <ol className="mt-3 flex flex-col gap-1.5">
        {shown.map(({ step, i }) => (
          <TraceStep key={i} step={step} marked={mine.has(i)} />
        ))}
      </ol>
      <button
        type="button"
        onClick={() => setAll(!all)}
        className="mt-2 rounded px-1 text-[13.5px] font-semibold text-stamp hover:underline"
      >
        {all ? 'Show only the steps behind this action' : `Show all ${calls.length} tool calls`}
      </button>
      {r.note && (
        <p className="mt-3 text-[13.5px] text-graphite">
          <span className="font-semibold text-ink">Its summary:</span> {r.note}
        </p>
      )}
    </section>
  )
}

function TraceStep({ step, marked }: { step: FixStep; marked: boolean }) {
  if (step.kind === 'say') {
    return (
      <li className="flex gap-2 py-0.5 pl-3 text-[13.5px] text-graphite italic">
        <MessageSquare className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <span>{step.text}</span>
      </li>
    )
  }
  if (step.kind === 'nudge') {
    return (
      <li className="flex gap-2 rounded-md bg-muted px-3 py-1.5 text-[13.5px]">
        <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-graphite" aria-hidden />
        <span>
          <span className="font-semibold">Kassenfest:</span> {step.text}
        </span>
      </li>
    )
  }
  const { call, result } = describe(step)
  return (
    <li
      className={cn(
        'rounded-md border bg-sheet text-[13px]',
        marked ? 'border-l-[3px] border-l-stamp' : 'opacity-75',
        !step.ok && 'border-l-[3px] border-l-fixable bg-fixable-wash',
      )}
    >
      <details>
        <summary className="cursor-pointer list-none px-3 py-1.5">
          <span className="font-mono text-[12.5px] font-semibold break-words text-ink">{call}</span>
          <span
            className={cn('mt-0.5 flex gap-1.5', step.ok ? 'text-graphite' : 'text-fixable')}
          >
            {!step.ok && <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
            <span>→ {result}</span>
          </span>
        </summary>
        <pre className="max-h-80 overflow-auto border-t bg-paper px-3 py-2 font-mono text-[11.5px] leading-snug whitespace-pre-wrap">
          {JSON.stringify({ arguments: step.args, result: step.result }, null, 1)}
        </pre>
      </details>
    </li>
  )
}
