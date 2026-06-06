import type {
  CaseRecord,
  CreateCaseRequest,
  ExtractRequest,
  ExtractResponse,
  OperateRequest,
  OperateResponse,
  RecoveryResponse,
  SelfImproveResponse,
  SimulateRecoveryRequest,
} from '~/types/api'

export function useHeartTwinApi() {
  const config = useRuntimeConfig()
  const base = config.public.apiBase as string

  async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
    const url = `${base}${path}`
    const resp = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...opts?.headers },
      ...opts,
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }))
      throw new Error(body?.detail || `API error ${resp.status}`)
    }
    return resp.json()
  }

  async function health() {
    return apiFetch<{ status: string; version: string; disclaimer: string }>('/health')
  }

  async function createCase(req: CreateCaseRequest) {
    return apiFetch<{ case_id: string; status: string; safety_disclaimer: string }>('/cases', {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  async function uploadFile(caseId: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    const url = `${base}/cases/${caseId}/files`
    const resp = await fetch(url, { method: 'POST', body: form })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }))
      throw new Error(body?.detail || `Upload failed ${resp.status}`)
    }
    return resp.json()
  }

  async function extract(caseId: string, req: ExtractRequest) {
    return apiFetch<ExtractResponse>(`/cases/${caseId}/extract`, {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  async function operate(caseId: string, req: OperateRequest = {}) {
    return apiFetch<OperateResponse>(`/cases/${caseId}/operate`, {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  async function simulateRecovery(caseId: string, req: SimulateRecoveryRequest = {}) {
    return apiFetch<RecoveryResponse>(`/cases/${caseId}/simulate-recovery`, {
      method: 'POST',
      body: JSON.stringify(req),
    })
  }

  async function selfImprove(caseId: string) {
    return apiFetch<SelfImproveResponse>(`/cases/${caseId}/self-improve`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  }

  async function getCase(caseId: string) {
    return apiFetch<CaseRecord>(`/cases/${caseId}`)
  }

  async function getTrace(caseId: string) {
    return apiFetch<{ case_id: string; traces: Array<Record<string, unknown>>; weave?: import('~/types/api').WeaveInfo }>(`/cases/${caseId}/trace`)
  }

  return {
    health,
    createCase,
    uploadFile,
    extract,
    operate,
    simulateRecovery,
    selfImprove,
    getCase,
    getTrace,
  }
}
