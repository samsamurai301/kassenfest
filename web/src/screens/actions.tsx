import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { type Action, type ActionList, useActions } from '@/api/client'
import { DueChip } from '@/components/finding'
import { LoadError, Loading, Page } from '@/components/shell'
import { Button } from '@/components/ui/button'
import { daysBetween, money, monthName, plural, weekdayDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

const KIND: Record<Action['kind'], string> = {
  folgeverordnung_request: 'Folgeverordnung request',
  stamp_request: 'Stamp request',
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

      <div className="mt-7 grid items-start gap-6 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <ol className="flex flex-col gap-2.5" aria-label="Actions by due date">
          {list.actions.map((a) => (
            <li key={a.id}>
              <Link
                to={`/months/${list.month}/actions?a=${a.id}`}
                replace
                aria-current={a.id === current?.id ? 'true' : undefined}
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

        {current && <Draft action={current} asOf={list.as_of} />}
      </div>
    </Page>
  )
}

function Draft({ action, asOf }: { action: Action; asOf: string }) {
  const [copied, setCopied] = useState(false)
  const { letter } = action
  const text = [...letter.recipient, '', letter.subject, '', letter.body].join('\n')

  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <section aria-labelledby="draft-title" className="min-w-0 lg:sticky lg:top-20">
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
        <p className="font-sans text-[11.5px] text-graphite">
          Pflegedienst Sonnenschein GmbH, Bahnhofstraße 12, 94469 Deggendorf
        </p>
        <address className="mt-3 font-serif text-[16px] leading-[1.45] not-italic">
          {letter.recipient.map((line) => (
            <span key={line} className="block">
              {line}
            </span>
          ))}
        </address>
        <p className="mt-8 text-right font-serif text-[15px]">
          Deggendorf, {asOf.split('-').reverse().join('.')}
        </p>
        <p className="mt-6 font-serif text-[16.5px] leading-snug font-semibold">{letter.subject}</p>
        <div className="mt-5 font-serif text-[16px] leading-[1.65] whitespace-pre-line">
          {letter.body}
        </div>
      </article>
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
