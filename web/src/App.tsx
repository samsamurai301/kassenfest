import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

// Placeholder shell: confirms web ↔ API wiring. The real screens land in Track C (docs/05 §5).
export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Kassenfest</h1>
      <p className="mt-2 text-muted-foreground">
        Checks every home-care bill before it goes to the Kasse.
      </p>

      <section className="mt-10 rounded-lg border p-5 text-sm">
        <h2 className="font-medium">Backend</h2>
        {health.isPending && <p className="mt-2 text-muted-foreground">Connecting…</p>}
        {health.isError && (
          <p className="mt-2 text-destructive">
            API unreachable ({health.error.message}). Is <code>make api</code> running?
          </p>
        )}
        {health.data && (
          <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
            <dt className="text-muted-foreground">Status</dt>
            <dd>{health.data.status}</dd>
            <dt className="text-muted-foreground">Model mode</dt>
            <dd>{health.data.llm_mode}</dd>
            <dt className="text-muted-foreground">API key</dt>
            <dd>{health.data.api_key_configured ? 'configured' : 'missing (replay only)'}</dd>
          </dl>
        )}
      </section>
    </main>
  )
}
