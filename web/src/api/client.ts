import { useQuery } from '@tanstack/react-query'
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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

export const api = {
  health: () => get<Health>('/api/health'),
  board: (month: string) => get<MonthBoard>(`/api/months/${month}/board`),
  actions: (month: string) => get<ActionList>(`/api/months/${month}/actions`),
  claim: (id: string) => get<ClaimDetail>(`/api/claims/${encodeURIComponent(id)}`),
  document: (id: string) => get<DocumentDetail>(`/api/documents/${encodeURIComponent(id)}`),
  timeline: (patientId: string) =>
    get<PatientTimeline>(`/api/patients/${encodeURIComponent(patientId)}/timeline`),
}

export const pageImageUrl = (documentId: string, page: number) =>
  `/api/documents/${encodeURIComponent(documentId)}/pages/${page}`

export const useBoard = (month: string) =>
  useQuery({ queryKey: ['board', month], queryFn: () => api.board(month) })
export const useActions = (month: string) =>
  useQuery({ queryKey: ['actions', month], queryFn: () => api.actions(month) })
export const useClaim = (id: string) =>
  useQuery({ queryKey: ['claim', id], queryFn: () => api.claim(id) })
export const useDocument = (id: string) =>
  useQuery({ queryKey: ['document', id], queryFn: () => api.document(id) })
export const useTimeline = (patientId: string) =>
  useQuery({ queryKey: ['timeline', patientId], queryFn: () => api.timeline(patientId) })
