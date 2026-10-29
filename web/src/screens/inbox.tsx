import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  FileUp,
  FolderUp,
  LoaderCircle,
  TriangleAlert,
} from 'lucide-react'
import { type DragEvent, type ReactNode, useRef, useState } from 'react'
import {
  api,
  type BatchDetail,
  type BatchSummary,
  type InboxDocument,
  type PipelineStep,
  useBatch,
  useBatchEvents,
  useBatches,
} from '@/api/client'
import { DEMO_MONTH, LoadError, Page } from '@/components/shell'
import { dateTime, monthName, plural } from '@/lib/format'
import { Link, navigate } from '@/lib/router'
import { cn } from '@/lib/utils'
import { DOC_TYPE } from '@/screens/claim'

const ACCEPT = ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.pdf', '.zip']

export function InboxScreen({ selected }: { selected: string | null }) {
  const batches = useBatches()
  const id = selected ?? batches.data?.batches[0]?.id ?? null
  const batch = useBatch(id)
  const live = ['reading', 'evidence', 'audit'].includes(batch.data?.phase ?? '')
  useBatchEvents(id, live)

  if (batches.isError) return <LoadError error={batches.error} />
  const earlier = batches.data?.batches.filter((b) => b.id !== id) ?? []
  return (
    <Page>
      <p className="text-[14px] text-graphite">Paperwork for {monthName(DEMO_MONTH)}</p>
      <h1 className="mt-1 text-[32px] leading-[1.15] font-bold tracking-[-0.015em] sm:text-[38px]">
        Inbox
      </h1>
      <p className="mt-3 max-w-[70ch] text-[15.5px] text-graphite">
        Drop the month's paperwork here: prescriptions, approval letters, visit logs and hospital
        letters, as scans, phone photos or PDFs. Kassenfest reads each page, links it to a patient
        and finds the evidence for every rule.
      </p>
      <Upload />
      {batch.isError && <p className="mt-8 text-blocked">{batch.error.message}</p>}
      {batch.data && <BatchView batch={batch.data} />}
      {earlier.length > 0 && <Earlier batches={earlier} />}
    </Page>
  )
}

// --- Upload ------------------------------------------------------------------------

type Sending = { files: number } | { error: string } | null

function readable(file: File) {
  const name = file.name.toLowerCase()
  return !name.startsWith('.') && ACCEPT.some((ext) => name.endsWith(ext))
}

/** Dropped files, with the files inside dropped folders; the folder's name for a label. */
async function dropped(data: DataTransfer): Promise<{ files: File[]; folder?: string }> {
  // Entries must be taken before the first await: the drop's data is gone after that.
  const entries = [...data.items].map((item) => item.webkitGetAsEntry()).filter((e) => e !== null)
  if (!entries.some((e) => e.isDirectory)) return { files: [...data.files] }
  const files: File[] = []
  async function walk(entry: FileSystemEntry): Promise<void> {
    if (entry.isFile) {
      files.push(await new Promise((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail)))
      return
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    for (;;) {
      const children = await new Promise<FileSystemEntry[]>((ok, fail) =>
        reader.readEntries(ok, fail),
      )
      if (children.length === 0) return
      for (const child of children) await walk(child)
    }
  }
  for (const entry of entries) await walk(entry)
  files.sort((a, b) => a.name.localeCompare(b.name))
  return { files, folder: entries.length === 1 ? entries[0].name : undefined }
}

function Upload() {
  const queryClient = useQueryClient()
  const [over, setOver] = useState(false)
  const [sending, setSending] = useState<Sending>(null)
  const filesInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const busy = sending !== null && 'files' in sending

  async function send(all: File[], label?: string) {
    const files = all.filter(readable)
    if (files.length === 0) {
      setSending({ error: 'None of these are images, PDFs or ZIPs.' })
      return
    }
    setSending({ files: files.length })
    try {
      const batch = await api.upload(files, label)
      queryClient.setQueryData(['batch', batch.id], batch)
      await queryClient.invalidateQueries({ queryKey: ['batches'] })
      setSending(null)
      navigate(`/inbox?batch=${batch.id}`, { replace: true })
    } catch (error) {
      setSending({ error: (error as Error).message })
    }
  }

  async function drop(event: DragEvent) {
    event.preventDefault()
    setOver(false)
    if (busy) return
    const { files, folder } = await dropped(event.dataTransfer)
    await send(files, folder)
  }

  function picked(input: HTMLInputElement | null) {
    const files = [...(input?.files ?? [])]
    const folder = files[0]?.webkitRelativePath.split('/')[0] || undefined
    if (input) input.value = '' // so picking the same files again still uploads them
    void send(files, folder)
  }

  return (
    <section
      aria-label="Upload paperwork"
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        'mt-7 flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-rule-strong bg-sheet px-6 py-9 text-center transition-colors',
        over && 'border-stamp bg-stamp-wash',
      )}
    >
      {busy ? (
        <LoaderCircle className="size-8 animate-spin text-stamp" aria-hidden />
      ) : (
        <FileUp className="size-8 text-stamp" strokeWidth={1.75} aria-hidden />
      )}
      <p className="text-[16px] font-semibold" role="status">
        {busy ? `Uploading ${plural(sending.files, 'file')}…` : 'Drop files or a folder here'}
      </p>
      <p className="text-[13.5px] text-graphite">PNG, JPG, HEIC or PDF, or a ZIP of them</p>
      <div className="mt-1 flex flex-wrap justify-center gap-2">
        <PickButton disabled={busy} onClick={() => filesInput.current?.click()}>
          <FileUp className="size-4" aria-hidden /> Choose files
        </PickButton>
        <PickButton disabled={busy} onClick={() => folderInput.current?.click()}>
          <FolderUp className="size-4" aria-hidden /> Choose a folder
        </PickButton>
      </div>
      <input
        ref={filesInput}
        type="file"
        multiple
        accept={ACCEPT.join(',')}
        className="hidden"
        onChange={(e) => picked(e.currentTarget)}
      />
      <input
        ref={folderInput}
        type="file"
        className="hidden"
        onChange={(e) => picked(e.currentTarget)}
        {...{ webkitdirectory: '' }}
      />
      {sending && 'error' in sending && (
        <p className="flex items-center gap-1.5 text-[14px] font-semibold text-blocked" role="alert">
          <CircleAlert className="size-4" aria-hidden /> {sending.error}
        </p>
      )}
    </section>
  )
}

function PickButton(props: { disabled: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      {...props}
      className="inline-flex h-9 items-center gap-2 rounded-full border bg-sheet px-3.5 text-[14px] font-semibold transition-colors hover:border-rule-strong disabled:opacity-50"
    />
  )
}

// --- One batch ---------------------------------------------------------------------

function BatchView({ batch }: { batch: BatchDetail }) {
  const finished = batch.done + batch.failed
  return (
    <section aria-labelledby="batch-title" className="mt-8 rounded-lg border bg-sheet">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-4">
        <div className="mr-auto">
          <h2 id="batch-title" className="text-[18px] font-bold">
            {batch.label ?? 'Upload'}
          </h2>
          <p className="text-[13.5px] text-graphite">
            {dateTime(batch.created_at)} · {plural(batch.files, 'file')}
          </p>
        </div>
        <Phase batch={batch} />
      </div>
      <div className="h-1 bg-rule" aria-hidden>
        <div
          className="h-full bg-stamp transition-[width] duration-300"
          style={{ width: `${batch.files ? (finished / batch.files) * 100 : 0}%` }}
        />
      </div>
      <ol className="divide-y">
        {batch.documents.map((doc) => (
          <DocumentRow key={doc.id} doc={doc} />
        ))}
      </ol>
    </section>
  )
}

function Phase({ batch }: { batch: BatchDetail }) {
  const finished = batch.done + batch.failed
  const failed = batch.failed ? `, ${batch.failed} couldn't be read` : ''
  switch (batch.phase) {
    case 'reading':
      return (
        <p className="flex items-center gap-2 text-[14px] font-semibold" role="status">
          <LoaderCircle className="size-4 animate-spin text-stamp" aria-hidden />
          Reading {finished} of {batch.files}…
        </p>
      )
    case 'evidence':
      return (
        <p className="flex items-center gap-2 text-[14px] font-semibold" role="status">
          <LoaderCircle className="size-4 animate-spin text-stamp" aria-hidden />
          All read. Marking the evidence on the pages…
        </p>
      )
    case 'audit':
      return (
        <p className="flex items-center gap-2 text-[14px] font-semibold" role="status">
          <LoaderCircle className="size-4 animate-spin text-stamp" aria-hidden />
          The Kasse&rsquo;s auditor is attacking the clean bills…
        </p>
      )
    case 'interrupted':
      return (
        <p className="flex items-center gap-2 text-[14px] font-semibold text-fixable">
          <TriangleAlert className="size-4" aria-hidden />
          Stopped when the server restarted. Upload the files again to finish.
        </p>
      )
    case 'done':
      return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="flex items-center gap-2 text-[14px] font-semibold" role="status">
            <CircleCheck className="size-4 text-ready" aria-hidden />
            {plural(batch.done, 'document')} read{failed}
          </p>
          <Link
            to={`/months/${DEMO_MONTH}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-full bg-ink px-4 text-[14px] font-semibold text-white"
          >
            See the {monthName(DEMO_MONTH).split(' ')[0]} bills
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      )
  }
}

const STEPS: { step: PipelineStep; label: string }[] = [
  { step: 'classified', label: 'Sorted' },
  { step: 'extracted', label: 'Read' },
  { step: 'linked', label: 'Linked' },
  { step: 'localized', label: 'Evidence' },
  { step: 'done', label: 'Done' },
]
const ORDER: PipelineStep[] = ['stored', ...STEPS.map((s) => s.step)]

/** What the pipeline is doing with a document now, after its last step. */
const NEXT: Partial<Record<PipelineStep, string>> = {
  stored: 'Sorting the page…',
  classified: 'Reading the fields…',
  extracted: 'Finding the patient…',
  linked: 'Finding the evidence…',
  localized: 'Saving…',
}

function DocumentRow({ doc }: { doc: InboxDocument }) {
  const reached = ORDER.indexOf(doc.step)
  const failed = doc.step === 'error'
  const working = !failed && doc.step !== 'done'
  const billing = doc.doc_type !== null && doc.doc_type !== 'other'
  return (
    <li className="grid gap-x-6 gap-y-2 px-5 py-3.5 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1.3fr)_9.5rem] md:items-center">
      <div className="min-w-0">
        <p className="truncate text-[14.5px] font-semibold" title={doc.filename}>
          {doc.filename}
        </p>
        <p className="text-[13px] text-graphite">
          {doc.pages ? plural(doc.pages, 'page') : 'no pages'}
        </p>
      </div>

      <div>
        <ol className="flex gap-1" aria-label={`Progress: ${failed ? 'failed' : doc.step}`}>
          {STEPS.map((s, i) => (
            <li
              key={s.step}
              title={s.label}
              className={cn(
                'h-1.5 flex-1 rounded-full bg-rule',
                i < reached && 'bg-stamp',
                failed && 'bg-blocked-edge',
              )}
            />
          ))}
        </ol>
        <p
          className={cn(
            'mt-1.5 flex items-center gap-1.5 text-[13px]',
            failed ? 'font-semibold text-blocked' : 'text-graphite',
          )}
        >
          {working && <LoaderCircle className="size-3.5 animate-spin" aria-hidden />}
          {failed
            ? (doc.error ?? "Couldn't be read")
            : doc.status === 'superseded'
              ? 'Replaced by a later upload'
              : working
                ? NEXT[doc.step]
                : billing
                  ? 'Read'
                  : 'Not a billing document'}
        </p>
      </div>

      <div className="min-w-0 text-[14px]">
        {doc.doc_type && <p className="font-semibold">{DOC_TYPE[doc.doc_type]}</p>}
        {doc.patient_id && (
          <Link
            to={`/patients/${doc.patient_id}`}
            className="text-graphite underline decoration-rule-strong underline-offset-2 hover:text-ink"
          >
            {doc.patient_name ?? doc.patient_id}
          </Link>
        )}
        {billing && doc.step === 'done' && !doc.patient_id && (
          <p className="text-fixable">No patient found</p>
        )}
      </div>

      <div className="flex items-center gap-3 md:justify-end">
        {doc.issues.length > 0 && (
          <span
            className="inline-flex items-center gap-1 text-[13px] font-semibold text-fixable"
            title={doc.issues.join('\n')}
          >
            <TriangleAlert className="size-3.5" aria-hidden />
            {doc.issues.length} to check
            <span className="sr-only">: {doc.issues.join('; ')}</span>
          </span>
        )}
        {billing && doc.status === 'done' && (
          <Link
            to={`/documents/${doc.id}`}
            className="text-[14px] font-semibold text-stamp underline underline-offset-2"
          >
            Open
          </Link>
        )}
      </div>
    </li>
  )
}

// --- Earlier uploads ---------------------------------------------------------------

function Earlier({ batches }: { batches: BatchSummary[] }) {
  return (
    <section aria-labelledby="earlier-title" className="mt-10">
      <h2 id="earlier-title" className="text-[15px] font-bold">
        Earlier uploads
      </h2>
      <ul className="mt-3 divide-y rounded-lg border bg-sheet">
        {batches.map((b) => (
          <li key={b.id}>
            <Link
              to={`/inbox?batch=${b.id}`}
              className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 px-5 py-3 hover:bg-paper"
            >
              <span className="font-semibold">{b.label ?? 'Upload'}</span>
              <span className="text-[13.5px] text-graphite">{dateTime(b.created_at)}</span>
              <span className="ml-auto text-[13.5px] text-graphite">
                {plural(b.files, 'file')} · {b.done} read
                {b.failed > 0 && `, ${b.failed} failed`}
                {b.phase === 'interrupted' && ' · stopped'}
                {['reading', 'evidence', 'audit'].includes(b.phase) && ' · reading now'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
