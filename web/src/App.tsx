import { useEffect } from 'react'
import { DEMO_MONTH, Page, Shell } from '@/components/shell'
import { Link, match, navigate, useLocation } from '@/lib/router'
import { ActionsScreen } from '@/screens/actions'
import { BoardScreen } from '@/screens/board'
import { ClaimScreen } from '@/screens/claim'
import { EvidenceScreen } from '@/screens/evidence'
import { InboxScreen } from '@/screens/inbox'
import { TimelineScreen } from '@/screens/timeline'

export default function App() {
  const { path, query } = useLocation()

  useEffect(() => {
    if (path === '/') navigate(`/months/${DEMO_MONTH}`, { replace: true })
  }, [path])

  if (path === '/inbox') {
    return (
      <Shell section="inbox">
        <InboxScreen selected={query.get('batch')} />
      </Shell>
    )
  }
  let params: Record<string, string> | null
  if ((params = match('/months/:month', path))) {
    return (
      <Shell section="bills">
        <BoardScreen month={params.month} filter={query.get('status')} />
      </Shell>
    )
  }
  if ((params = match('/months/:month/actions', path))) {
    return (
      <Shell section="actions">
        <ActionsScreen month={params.month} selected={query.get('a')} />
      </Shell>
    )
  }
  if ((params = match('/claims/:id', path))) {
    return (
      <Shell section="bills">
        <ClaimScreen id={params.id} />
      </Shell>
    )
  }
  if ((params = match('/documents/:id', path))) {
    return (
      <Shell section="bills">
        <EvidenceScreen
          id={params.id}
          page={Number(query.get('page') ?? 0)}
          findingId={query.get('finding')}
          claimId={query.get('claim')}
          fieldPath={query.get('field')}
        />
      </Shell>
    )
  }
  if ((params = match('/patients/:id', path))) {
    return (
      <Shell section="bills">
        <TimelineScreen id={params.id} />
      </Shell>
    )
  }
  return (
    <Shell section={null}>
      {path !== '/' && (
        <Page>
          <h1 className="text-[24px] font-bold">Nothing here</h1>
          <p className="mt-2 text-graphite">
            This address doesn't match a screen.{' '}
            <Link to={`/months/${DEMO_MONTH}`} className="font-semibold text-stamp underline">
              Go to the October bills
            </Link>
          </p>
        </Page>
      )}
    </Shell>
  )
}
