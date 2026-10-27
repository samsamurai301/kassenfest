import { type AnchorHTMLAttributes, type MouseEvent, useSyncExternalStore } from 'react'

// A few screens and no nested layouts: history API + one hook instead of a router library.

const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('popstate', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('popstate', listener)
  }
}

export function navigate(to: string, { replace = false } = {}) {
  if (to === location.pathname + location.search) return
  history[replace ? 'replaceState' : 'pushState'](null, '', to)
  for (const listener of listeners) listener()
  if (!replace) window.scrollTo(0, 0)
}

const snapshot = () => location.pathname + location.search

export function useLocation() {
  const href = useSyncExternalStore(subscribe, snapshot)
  const url = new URL(href, location.origin)
  return { path: url.pathname, query: url.searchParams }
}

/** Matches '/claims/:id' against a path; returns the params or null. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split('/')
  const got = path.replace(/\/$/, '').split('/')
  if (want.length !== got.length) return null
  const params: Record<string, string> = {}
  for (const [i, part] of want.entries()) {
    if (part.startsWith(':')) params[part.slice(1)] = decodeURIComponent(got[i])
    else if (part !== got[i]) return null
  }
  return params
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & { to: string; replace?: boolean }

export function Link({ to, replace, onClick, ...rest }: LinkProps) {
  function handle(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event)
    if (event.defaultPrevented || event.button !== 0) return
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to, { replace })
  }
  return <a href={to} onClick={handle} {...rest} />
}
