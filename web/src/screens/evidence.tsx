import { ArrowLeft, Crosshair, Maximize2, Minus, Plus } from 'lucide-react'
import {
  type KeyboardEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  type DocumentDetail,
  type DocumentField,
  type Finding,
  type PixelBox,
  type Severity,
  pageImageUrl,
  useDocument,
} from '@/api/client'
import { FindingCard } from '@/components/finding'
import { DEMO_MONTH, LoadError, Loading } from '@/components/shell'
import { SEVERITY } from '@/components/status'
import { Button } from '@/components/ui/button'
import { longDate } from '@/lib/format'
import { Link } from '@/lib/router'
import { docTypeLabel } from '@/screens/claim'

type Mark = { key: string; findingId: string; severity: Severity; label: string; box: PixelBox }
type View = { scale: number; x: number; y: number }

export function EvidenceScreen({
  id,
  page,
  findingId,
  claimId,
  fieldPath = null,
}: {
  id: string
  page: number
  findingId: string | null
  claimId: string | null
  fieldPath?: string | null
}) {
  const doc = useDocument(id)
  if (doc.isPending) return <Loading what="the document" />
  if (doc.isError) return <LoadError error={doc.error} />
  return (
    <EvidenceView
      key={`${id}:${page}`}
      detail={doc.data}
      page={page}
      initialFinding={findingId}
      initialField={fieldPath}
      claimId={claimId}
    />
  )
}

function EvidenceView({
  detail,
  page,
  initialFinding,
  initialField,
  claimId,
}: {
  detail: DocumentDetail
  page: number
  initialFinding: string | null
  initialField: string | null
  claimId: string | null
}) {
  const { document: doc, findings } = detail
  const size = doc.pages[page] ?? doc.pages[0]
  const marks = useMemo(() => marksOnPage(findings, doc.id, page), [findings, doc.id, page])
  const [active, setActive] = useState<string | null>(initialFinding)
  const [hovered, setHovered] = useState<string | null>(null)
  const [field, setField] = useState<DocumentField | null>(null)
  // A link may point at one field (the auditor's debate does): outlined until another is chosen.
  const pinned = useMemo(
    () => detail.fields.find((f) => f.path === initialField && f.page === page) ?? null,
    [detail.fields, initialField, page],
  )
  const [focus, setFocus] = useState(
    () =>
      focusFor(marks, initialFinding) ??
      (pinned ? { box: pinned.box as PixelBox, seq: Date.now() } : null),
  )

  const shown = hovered ?? active
  const claim = claimId ?? detail.claim_ids[0] ?? null
  const select = (findingId: string | null) => {
    setActive(findingId)
    if (findingId) setFocus(focusFor(marks, findingId))
  }

  return (
    <div className="grid h-[calc(100svh-3.5rem)] grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,1fr)_420px] lg:grid-rows-1">
      <PageCanvas
        src={pageImageUrl(doc.id, page)}
        alt={`${docTypeLabel(doc)}: ${doc.title}`}
        width={size.width}
        height={size.height}
        marks={marks}
        shown={shown}
        field={field ?? pinned}
        focus={focus}
        onHover={setHovered}
        onSelect={select}
      />
      <aside className="flex min-h-0 flex-col overflow-y-auto border-l bg-paper">
        <div className="border-b bg-sheet px-5 pt-4 pb-5">
          <Link
            to={claim ? `/claims/${encodeURIComponent(claim)}` : `/months/${DEMO_MONTH}`}
            className="inline-flex items-center gap-1.5 rounded text-[14px] font-semibold text-graphite hover:text-stamp"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {claim ? 'Back to the bill' : 'Back to the bills'}
          </Link>
          <p className="mt-3 text-[13px] font-semibold text-graphite">{docTypeLabel(doc)}</p>
          <h1 className="text-[21px] leading-tight font-bold">{doc.title}</h1>
          {doc.received_on && (
            <p className="mt-1 text-[13.5px] text-graphite">
              Received {longDate(doc.received_on)}, page {page + 1} of {doc.pages.length}
            </p>
          )}
        </div>

        <section aria-labelledby="page-findings" className="px-5 pt-5">
          <h2 id="page-findings" className="text-[16px] font-bold">
            {marks.length ? 'Findings on this page' : 'No findings on this page'}
          </h2>
          <div className="mt-3 flex flex-col gap-3">
            {findings
              .filter((f) => marks.some((m) => m.findingId === f.id))
              .map((f) => (
                <FindingCard
                  key={f.id}
                  finding={f}
                  showEvidence={false}
                  active={f.id === shown}
                  onActivate={setHovered}
                  footer={
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-3"
                      onClick={() => select(f.id)}
                    >
                      <Crosshair aria-hidden />
                      Show on page
                    </Button>
                  }
                />
              ))}
          </div>
        </section>

        <section aria-labelledby="page-fields" className="px-5 pt-6 pb-6">
          <h2 id="page-fields" className="text-[16px] font-bold">
            Read from the page
          </h2>
          <p className="mt-0.5 text-[13px] text-graphite">Point at a field to see where it is.</p>
          <ul
            className="mt-3 divide-y rounded-lg border bg-sheet"
            onMouseLeave={() => setField(null)}
          >
            {detail.fields.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 px-3 py-2 text-left hover:bg-stamp-wash/70 focus-visible:bg-stamp-wash/70"
                  onMouseEnter={() => setField(f)}
                  onFocus={() => setField(f)}
                  onBlur={() => setField(null)}
                  onClick={() => setFocus({ box: f.box as PixelBox, seq: Date.now() })}
                >
                  <span className="truncate text-[13px] text-graphite" lang="de">
                    {f.label}
                  </span>
                  <FieldValue field={f} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  )
}

function FieldValue({ field }: { field: DocumentField }) {
  if (field.status !== 'present') {
    return (
      <span className="rounded bg-blocked-wash px-1.5 text-[12.5px] font-bold text-blocked">
        {field.status === 'empty' ? 'Empty' : 'Unreadable'}
      </span>
    )
  }
  const value = field.value === 'present' ? 'Present' : field.value
  return <span className="text-[13.5px] font-semibold tabular">{value}</span>
}

function marksOnPage(findings: Finding[], docId: string, page: number): Mark[] {
  return findings.flatMap((f) =>
    (f.evidence ?? []).flatMap((ev, i) =>
      ev.document_id === docId && (ev.page ?? 0) === page && ev.box
        ? [
            {
              key: `${f.id}:${i}`,
              findingId: f.id,
              severity: f.severity,
              label: ev.note ?? f.rule_id,
              box: ev.box as PixelBox,
            },
          ]
        : [],
    ),
  )
}

function focusFor(marks: Mark[], findingId: string | null) {
  const own = marks.filter((m) => m.findingId === findingId)
  if (!own.length) return null
  const box: PixelBox = [
    Math.min(...own.map((m) => m.box[0])),
    Math.min(...own.map((m) => m.box[1])),
    Math.max(...own.map((m) => m.box[2])),
    Math.max(...own.map((m) => m.box[3])),
  ]
  return { box, seq: Date.now() }
}

const MIN_SCALE = 0.15
const MAX_SCALE = 4
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

/**
 * The page with its evidence boxes, zoomable (wheel, buttons, +/-/0 keys) and pannable
 * (drag, arrow keys). While a finding is shown, everything but its boxes is dimmed.
 */
function PageCanvas({
  src,
  alt,
  width,
  height,
  marks,
  shown,
  field,
  focus,
  onHover,
  onSelect,
}: {
  src: string
  alt: string
  width: number
  height: number
  marks: Mark[]
  shown: string | null
  field: DocumentField | null
  focus: { box: PixelBox; seq: number } | null
  onHover: (findingId: string | null) => void
  onSelect: (findingId: string | null) => void
}) {
  const maskId = useId()
  const ref = useRef<HTMLDivElement>(null)
  const [frame, setFrame] = useState({ w: 0, h: 0 })
  const [view, setView] = useState<View | null>(null)
  const [animate, setAnimate] = useState(false)
  const drag = useRef<{ x: number; y: number; from: View; moved: boolean } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // Measure now so the first paint already shows the page; the observer keeps it current.
    const rect = el.getBoundingClientRect()
    setFrame({ w: rect.width, h: rect.height })
    const observer = new ResizeObserver(([entry]) =>
      setFrame({ w: entry.contentRect.width, h: entry.contentRect.height }),
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const fitView = useCallback((): View => {
    const scale = Math.min(frame.w / width, frame.h / height) * 0.94
    return { scale, x: (frame.w - width * scale) / 2, y: (frame.h - height * scale) / 2 }
  }, [frame, width, height])

  const boxView = useCallback(
    (box: PixelBox): View => {
      const pad = 90
      const fit = Math.min(frame.w / width, frame.h / height)
      const scale = clamp(
        Math.min(frame.w / (box[2] - box[0] + pad * 2), frame.h / (box[3] - box[1] + pad * 2)),
        fit,
        1.25,
      )
      const cx = (box[0] + box[2]) / 2
      const cy = (box[1] + box[3]) / 2
      return { scale, x: frame.w / 2 - cx * scale, y: frame.h / 2 - cy * scale }
    },
    [frame, width, height],
  )

  // Until the first zoom or pan the page is fitted; then it glides to the requested finding.
  const ready = frame.w > 0 && frame.h > 0
  const current = view ?? (ready ? fitView() : null)

  useEffect(() => {
    if (!ready || !focus) return
    const id = requestAnimationFrame(() => {
      setAnimate(true)
      setView(boxView(focus.box))
    })
    return () => cancelAnimationFrame(id)
  }, [ready, focus, boxView])

  const zoomAt = useCallback(
    (factor: number, px: number, py: number, smooth: boolean) => {
      setAnimate(smooth)
      setView((prev) => {
        const v = prev ?? fitView()
        const scale = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE)
        const k = scale / v.scale
        return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k }
      })
    },
    [fitView],
  )

  useEffect(() => {
    const el = ref.current
    if (!el) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      const rect = el!.getBoundingClientRect()
      const factor = Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015))
      zoomAt(factor, event.clientX - rect.left, event.clientY - rect.top, false)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!current || event.button !== 0) return
    drag.current = { x: event.clientX, y: event.clientY, from: current, moved: false }
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (!d) return
    const dx = event.clientX - d.x
    const dy = event.clientY - d.y
    if (!d.moved && Math.hypot(dx, dy) < 4) return
    if (!d.moved) event.currentTarget.setPointerCapture(event.pointerId)
    d.moved = true
    setAnimate(false)
    setView({ ...d.from, x: d.from.x + dx, y: d.from.y + dy })
  }
  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    const d = drag.current
    drag.current = null
    // A plain click on the page (not on a box, not a drag) lifts the spotlight.
    const onMark = (event.target as Element).closest('[data-mark]')
    if (d && !d.moved && !onMark && event.type === 'pointerup') onSelect(null)
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const center = [frame.w / 2, frame.h / 2] as const
    const pan = (dx: number, dy: number) => {
      setAnimate(true)
      setView((prev) => {
        const v = prev ?? fitView()
        return { ...v, x: v.x + dx, y: v.y + dy }
      })
    }
    const keys: Record<string, () => void> = {
      '+': () => zoomAt(1.25, ...center, true),
      '=': () => zoomAt(1.25, ...center, true),
      '-': () => zoomAt(0.8, ...center, true),
      '0': () => {
        setAnimate(true)
        setView(fitView())
      },
      ArrowLeft: () => pan(80, 0),
      ArrowRight: () => pan(-80, 0),
      ArrowUp: () => pan(0, 80),
      ArrowDown: () => pan(0, -80),
      Escape: () => onSelect(null),
    }
    const run = keys[event.key]
    if (run) {
      event.preventDefault()
      run()
    }
  }

  const lit = marks.filter((m) => m.findingId === shown)
  const scale = current?.scale ?? 1
  const tagSize = 13 / scale

  return (
    <div
      ref={ref}
      className="relative min-h-[60svh] cursor-grab touch-none overflow-hidden bg-[#dde2e5] select-none active:cursor-grabbing focus-visible:outline-offset-[-3px] lg:min-h-0"
      tabIndex={0}
      role="application"
      aria-label={`${alt}. Scroll or press plus and minus to zoom, drag or use the arrow keys to move, 0 to fit.`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    >
      {current && (
        <div
          className="absolute top-0 left-0 origin-top-left will-change-transform"
          style={{
            width,
            height,
            transform: `translate(${current.x}px, ${current.y}px) scale(${current.scale})`,
            transition: animate ? 'transform 520ms cubic-bezier(0.22, 0.8, 0.25, 1)' : 'none',
          }}
        >
          <img
            src={src}
            alt={alt}
            width={width}
            height={height}
            draggable={false}
            className="block bg-white shadow-[0_2px_24px_-6px_rgb(28_34_54/0.35)]"
          />
          <svg
            className="absolute inset-0 overflow-visible"
            viewBox={`0 0 ${width} ${height}`}
            width={width}
            height={height}
          >
            <defs>
              <mask id={maskId}>
                <rect width={width} height={height} fill="white" />
                {lit.map((m) => (
                  <rect
                    key={m.key}
                    x={m.box[0] - 10}
                    y={m.box[1] - 10}
                    width={m.box[2] - m.box[0] + 20}
                    height={m.box[3] - m.box[1] + 20}
                    rx={8}
                    fill="black"
                  />
                ))}
              </mask>
            </defs>
            <rect
              width={width}
              height={height}
              fill="rgb(28 34 54)"
              mask={`url(#${CSS.escape(maskId)})`}
              opacity={lit.length ? 0.4 : 0}
              pointerEvents="none"
              style={{ transition: 'opacity 260ms ease' }}
            />
            {marks.map((m) => {
              const on = m.findingId === shown
              // While one finding is spotlit, the others' boxes step aside.
              if (shown && !on) return null
              const stroke = SEVERITY[m.severity].stroke
              return (
                <g key={m.key} data-mark>
                  <rect
                    x={m.box[0] - 4}
                    y={m.box[1] - 4}
                    width={m.box[2] - m.box[0] + 8}
                    height={m.box[3] - m.box[1] + 8}
                    rx={6}
                    fill={stroke}
                    fillOpacity={on ? 0.04 : 0.1}
                    stroke={stroke}
                    strokeWidth={on ? 3.5 : 2}
                    strokeDasharray={on ? undefined : '9 6'}
                    vectorEffect="non-scaling-stroke"
                    className="cursor-pointer"
                    onPointerEnter={() => onHover(m.findingId)}
                    onPointerLeave={() => onHover(null)}
                    onPointerUp={() => onSelect(m.findingId)}
                  />
                  {on && <BoxTag box={m.box} text={m.label} size={tagSize} fill={stroke} />}
                </g>
              )
            })}
            {field && (
              <g pointerEvents="none">
                <rect
                  x={field.box[0] - 4}
                  y={field.box[1] - 4}
                  width={field.box[2] - field.box[0] + 8}
                  height={field.box[3] - field.box[1] + 8}
                  rx={6}
                  fill="var(--stamp)"
                  fillOpacity={0.1}
                  stroke="var(--stamp)"
                  strokeWidth={2.5}
                  vectorEffect="non-scaling-stroke"
                />
                <BoxTag
                  box={field.box as PixelBox}
                  text={field.label}
                  size={tagSize}
                  fill="var(--stamp)"
                />
              </g>
            )}
          </svg>
        </div>
      )}

      <div
        className="absolute top-3 left-3 flex items-center gap-1 rounded-lg border bg-sheet p-1 shadow-sm"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom out"
          onClick={() => zoomAt(0.8, frame.w / 2, frame.h / 2, true)}
        >
          <Minus aria-hidden />
        </Button>
        <span className="w-12 text-center text-[13px] font-semibold tabular" aria-live="polite">
          {Math.round(scale * 100)}%
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Zoom in"
          onClick={() => zoomAt(1.25, frame.w / 2, frame.h / 2, true)}
        >
          <Plus aria-hidden />
        </Button>
        <span className="mx-1 h-5 w-px bg-rule" aria-hidden />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setAnimate(true)
            setView(fitView())
          }}
        >
          <Maximize2 aria-hidden />
          Whole page
        </Button>
      </div>
      <p className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-sheet/90 px-2 py-1 text-[12.5px] text-graphite">
        Scroll to zoom, drag to move
      </p>
    </div>
  )
}

/** A label above a box that stays the same size on screen at any zoom. */
function BoxTag({
  box,
  text,
  size,
  fill,
}: {
  box: PixelBox
  text: string
  size: number
  fill: string
}) {
  const padX = size * 0.6
  const h = size * 1.75
  const w = text.length * size * 0.56 + padX * 2
  const y = box[1] - 4 - h - size * 0.35
  return (
    <g pointerEvents="none">
      <rect x={box[0] - 4} y={y} width={w} height={h} rx={size * 0.35} fill={fill} />
      <text
        x={box[0] - 4 + padX}
        y={y + h * 0.68}
        fontSize={size}
        fontWeight={700}
        fill="white"
        fontFamily="Atkinson Hyperlegible Next Variable, sans-serif"
      >
        {text}
      </text>
    </g>
  )
}
