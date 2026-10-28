import type { ReactNode } from 'react'
import { Link } from '@/lib/router'
import { cn } from '@/lib/utils'

export const DEMO_MONTH = '2026-10'

function Mark() {
  // A rubber stamp with a tick: the "geprüft" mark a billing clerk would put on a checked bill.
  return (
    <svg viewBox="0 0 28 28" className="size-7" aria-hidden>
      <rect
        x="3.5"
        y="3.5"
        width="21"
        height="21"
        rx="4"
        fill="none"
        stroke="var(--stamp)"
        strokeWidth="2.25"
        transform="rotate(-8 14 14)"
      />
      <path
        d="M9 14.5l3.4 3.4L19.5 10"
        fill="none"
        stroke="var(--stamp)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="rotate(-8 14 14)"
      />
    </svg>
  )
}

type Section = 'inbox' | 'bills' | 'actions' | null

export function Shell({ section, children }: { section: Section; children: ReactNode }) {
  const nav: { id: Section; label: string; to: string }[] = [
    { id: 'inbox', label: 'Inbox', to: '/inbox' },
    { id: 'bills', label: 'Bills', to: `/months/${DEMO_MONTH}` },
    { id: 'actions', label: 'Actions', to: `/months/${DEMO_MONTH}/actions` },
  ]
  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-30 border-b bg-sheet/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1360px] items-center gap-8 px-4 sm:px-6">
          <Link to={`/months/${DEMO_MONTH}`} className="flex items-center gap-2 rounded-md">
            <Mark />
            <span className="text-[18px] font-bold tracking-[-0.01em]">Kassenfest</span>
          </Link>
          <nav className="flex h-full items-stretch gap-1" aria-label="Main">
            {nav.map((item) => (
              <Link
                key={item.label}
                to={item.to}
                aria-current={section === item.id ? 'page' : undefined}
                className={cn(
                  'flex items-center border-b-2 border-transparent px-3 text-[14px] font-semibold text-graphite transition-colors hover:text-ink',
                  'aria-[current=page]:border-stamp aria-[current=page]:text-ink',
                )}
              >
                {item.label}
                {item.id === 'actions' && <span className="hidden sm:inline">&nbsp;& deadlines</span>}
              </Link>
            ))}
          </nav>
          <div className="ml-auto hidden text-right leading-tight md:block">
            <p className="text-[14px] font-semibold">Pflegedienst Sonnenschein GmbH</p>
            <p className="text-[12.5px] text-graphite">Deggendorf, Bavaria</p>
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t">
        <p className="mx-auto max-w-[1360px] px-4 py-3 text-[12.5px] text-graphite sm:px-6">
          Synthetic demo data: every patient, document and ID is invented. Prices are illustrative.
        </p>
      </footer>
    </div>
  )
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('mx-auto w-full max-w-[1360px] px-4 py-8 sm:px-6', className)}>
      {children}
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <Page>
      <p className="text-graphite" role="status">
        Loading {what}…
      </p>
    </Page>
  )
}

export function LoadError({ error }: { error: Error }) {
  return (
    <Page>
      <div className="max-w-xl rounded-lg border border-l-4 border-l-blocked-edge bg-sheet p-5">
        <p className="font-semibold">Couldn't load this page.</p>
        <p className="mt-1 text-graphite">{error.message}</p>
        <p className="mt-3 text-[13.5px] text-graphite">
          Is the API running? Start it with <code className="font-semibold">make dev</code>.
        </p>
      </div>
    </Page>
  )
}
