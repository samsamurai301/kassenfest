import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { components } from './schema'

// Types come from the backend's OpenAPI spec: run `make api-types` after changing API models.
type Schemas = components['schemas']
export type Health = Schemas['Health']
export type MonthBoard = Schemas['MonthBoard']
export type BoardCard = Schemas['BoardCard']
export type ClaimDetail = Schemas['ClaimDetail']
export type Claim = Schemas['Claim']
export type ClaimLine = Schemas['ClaimLine']
export type Finding = Schemas['Finding']
export type Evidence = Schemas['Evidence']
export type DocumentInfo = Schemas['DocumentInfo']
export type DocumentDetail = Schemas['DocumentDetail']
export type DocumentField = Schemas['DocumentField']
export type PatientTimeline = Schemas['PatientTimeline']
export type Action = Schemas['Action']
export type ActionList = Schemas['ActionList']
export type Payer = Schemas['Payer']
export type ClaimStatus = BoardCard['status']
export type Severity = Finding['severity']
export type PixelBox = [number, number, number, number]
export type BatchList = Schemas['BatchList']
export type BatchSummary = Schemas['BatchSummary']
export type BatchDetail = Schemas['BatchDetail']
export type BatchEvent = Schemas['BatchEvent']
export type InboxDocument = Schemas['InboxDocument']
export type PipelineStep = InboxDocument['step']
export type ClaimAudit = Schemas['ClaimAudit']
export type AuditStatus = Schemas['AuditStatus']
export type ObjectionVerdict = Schemas['ObjectionVerdict']
export type FixerStatus = Schemas['FixerStatus']
export type FixRun = Schemas['FixRun']
export type FixStep = Schemas['FixStep']

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

const get = async <T,>(path: string) => json<T>(await fetch(path))

async function startAudit(claimId: string): Promise<AuditStatus> {
  const path = `/api/claims/${encodeURIComponent(claimId)}/audit`
  return json<AuditStatus>(await fetch(path, { method: 'POST' }))
}

async function draftActions(month: string): Promise<FixerStatus> {
  return json<FixerStatus>(await fetch(`/api/months/${month}/actions/draft`, { method: 'POST' }))
}

async function upload(files: File[], label?: string): Promise<BatchDetail> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)
  if (label) form.append('label', label)
  return json<BatchDetail>(await fetch('/api/batches', { method: 'POST', body: form }))
}

export const api = {
  health: () => get<Health>('/api/health'),
  board: (month: string) => get<MonthBoard>(`/api/months/${month}/board`),
  actions: (month: string) => get<ActionList>(`/api/months/${month}/actions`),
  claim: (id: string) => get<ClaimDetail>(`/api/claims/${encodeURIComponent(id)}`),
  document: (id: string) => get<DocumentDetail>(`/api/documents/${encodeURIComponent(id)}`),
  timeline: (patientId: string) =>
    get<PatientTimeline>(`/api/patients/${encodeURIComponent(patientId)}/timeline`),
  batches: () => get<BatchList>('/api/batches'),
  batch: (id: string) => get<BatchDetail>(`/api/batches/${encodeURIComponent(id)}`),
  fixRun: (id: string) => get<FixRun>(`/api/fix-runs/${encodeURIComponent(id)}`),
  upload,
  startAudit,
  draftActions,
}

export const pageImageUrl = (documentId: string, page: number) =>
  `/api/documents/${encodeURIComponent(documentId)}/pages/${page}`

export const useBoard = (month: string) =>
  useQuery({ queryKey: ['board', month], queryFn: () => api.board(month) })
export const useActions = (month: string) =>
  useQuery({
    queryKey: ['actions', month],
    queryFn: () => api.actions(month),
    // While the fixer drafts, look again until its actions are in.
    refetchInterval: (query) => (query.state.data?.fixer.state === 'running' ? 2000 : false),
  })

/** Let the fixer draft the actions for findings without a current draft; the list then polls. */
export function useDraftActions(month: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.draftActions(month),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['actions', month] }),
  })
}

/** How the fixer drafted an action: every tool call of its run. Runs never change. */
export const useFixRun = (id: string | null | undefined) =>
  useQuery({
    queryKey: ['fix-run', id],
    queryFn: () => api.fixRun(id!),
    enabled: !!id,
    staleTime: Infinity,
  })
export const useClaim = (id: string) =>
  useQuery({
    queryKey: ['claim', id],
    queryFn: () => api.claim(id),
    // While the auditor attacks the bill, look again until it has its verdicts.
    refetchInterval: (query) => (query.state.data?.audit.state === 'running' ? 2000 : false),
  })

/** Let the auditor attack a clean bill; the claim then polls until the verdicts are in. */
export function useStartAudit(claimId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.startAudit(claimId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['claim', claimId] }),
  })
}
export const useDocument = (id: string) =>
  useQuery({ queryKey: ['document', id], queryFn: () => api.document(id) })
export const useTimeline = (patientId: string) =>
  useQuery({ queryKey: ['timeline', patientId], queryFn: () => api.timeline(patientId) })
export const useBatches = () => useQuery({ queryKey: ['batches'], queryFn: api.batches })
export const useBatch = (id: string | null) =>
  useQuery({ queryKey: ['batch', id], queryFn: () => api.batch(id!), enabled: id !== null })

/** The batch after one server-sent event: that document's new state, the batch's phase. */
export function applyEvent(batch: BatchDetail, event: BatchEvent): BatchDetail {
  let documents = batch.documents
  const doc = event.document
  if (doc) {
    documents = documents.some((d) => d.id === doc.id)
      ? documents.map((d) => (d.id === doc.id ? doc : d))
      : [...documents, doc]
  }
  return {
    ...batch,
    phase: event.phase,
    documents,
    files: documents.length,
    done: documents.filter((d) => d.status === 'done' || d.status === 'superseded').length,
    failed: documents.filter((d) => d.status === 'error').length,
  }
}

/**
 * Follows a batch while the server reads it: every event updates the cached batch, and
 * when it's done everything derived from the month (board, bills, documents) refetches.
 */
export function useBatchEvents(id: string | null, live: boolean) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (id === null || !live) return
    let lastSeq = 0
    const source = new EventSource(`/api/batches/${encodeURIComponent(id)}/events`)
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as BatchEvent
      if (event.seq <= lastSeq) return // a reconnect replays from the first event
      lastSeq = event.seq
      queryClient.setQueryData<BatchDetail>(['batch', id], (old) => old && applyEvent(old, event))
      if (event.kind === 'phase' && event.phase === 'done') {
        source.close()
        void queryClient.invalidateQueries()
      }
    }
    source.onerror = () => {
      // Dropped, or this server isn't reading the batch (it restarted): ask for the stored state.
      void queryClient.invalidateQueries({ queryKey: ['batch', id] })
      void queryClient.invalidateQueries({ queryKey: ['batches'] })
    }
    return () => source.close()
  }, [id, live, queryClient])
}
