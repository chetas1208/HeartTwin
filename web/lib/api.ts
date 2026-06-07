/*
 * Typed HTTP client for the HeartTwin Lab backend (FastAPI, /api/v1/*).
 *
 * Every method maps one backend endpoint. Errors are thrown as ApiRequestError
 * with the backend's `detail` and `safety_disclaimer` preserved. There is NO
 * silent fallback and NO mock data: a failed request throws so callers (the
 * store, components) surface the real problem.
 *
 * Base URL comes from NEXT_PUBLIC_API_BASE (e.g. http://localhost:8000/api/v1).
 * The SSE trace stream and the Redis status snapshot are exposed as URL/derived
 * helpers because EventSource and SSE-only data do not fit fetch().
 */

import type {
  CreateCaseRequest,
  CreateCaseResponse,
  ExtractRequest,
  ExtractResponse,
  OperateRequest,
  OperateResponse,
  RecoveryResponse,
  SelfImproveResponse,
  SimulateRecoveryRequest,
  SystemCheckResponse,
  TraceResponse,
  UploadedFile,
} from "@/types/api";
import type { CaseRecord } from "@/types/api";

function resolveApiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE;
  if (!base) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not set. Create web/.env.local with " +
        "NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1",
    );
  }
  return base.replace(/\/$/, "");
}

/** Origin without the /api/v1 suffix (for endpoints mounted at the root). */
function apiOrigin(): string {
  try {
    return new URL(resolveApiBase()).origin;
  } catch {
    return resolveApiBase().replace(/\/api\/v1$/, "");
  }
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly safetyDisclaimer?: string;
  readonly endpoint: string;

  constructor(args: {
    status: number;
    detail: string;
    endpoint: string;
    safetyDisclaimer?: string;
  }) {
    super(`[${args.status}] ${args.endpoint}: ${args.detail}`);
    this.name = "ApiRequestError";
    this.status = args.status;
    this.detail = args.detail;
    this.safetyDisclaimer = args.safetyDisclaimer;
    this.endpoint = args.endpoint;
  }
}

async function parseError(
  response: Response,
  endpoint: string,
): Promise<ApiRequestError> {
  let detail = response.statusText || "Request failed";
  let safetyDisclaimer: string | undefined;
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      error?: unknown;
      safety_disclaimer?: string;
    };
    if (typeof body.detail === "string") detail = body.detail;
    else if (typeof body.error === "string") detail = body.error;
    else if (body.detail) detail = JSON.stringify(body.detail);
    safetyDisclaimer = body.safety_disclaimer;
  } catch {
    /* non-JSON error body — keep status text */
  }
  return new ApiRequestError({
    status: response.status,
    detail,
    endpoint,
    safetyDisclaimer,
  });
}

async function request<T>(
  path: string,
  init?: RequestInit,
  origin?: string,
): Promise<T> {
  const base = origin ?? resolveApiBase();
  const url = `${base}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init?.headers,
      },
    });
  } catch (cause) {
    throw new ApiRequestError({
      status: 0,
      endpoint: path,
      detail:
        cause instanceof Error
          ? `Network error: ${cause.message}`
          : "Network error: backend unreachable",
    });
  }
  if (!response.ok) {
    throw await parseError(response, path);
  }
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

export function createCase(
  body: CreateCaseRequest = {},
): Promise<CreateCaseResponse> {
  return request<CreateCaseResponse>("/cases", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getCase(caseId: string): Promise<CaseRecord> {
  return request<CaseRecord>(`/cases/${encodeURIComponent(caseId)}`);
}

export function uploadFile(
  caseId: string,
  file: File,
): Promise<UploadedFile & { safety_disclaimer: string }> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadedFile & { safety_disclaimer: string }>(
    `/cases/${encodeURIComponent(caseId)}/files`,
    { method: "POST", body: form },
  );
}

export function extract(
  caseId: string,
  body: ExtractRequest,
): Promise<ExtractResponse> {
  return request<ExtractResponse>(
    `/cases/${encodeURIComponent(caseId)}/extract`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function operate(
  caseId: string,
  body: OperateRequest = {},
): Promise<OperateResponse> {
  return request<OperateResponse>(
    `/cases/${encodeURIComponent(caseId)}/operate`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function simulateRecovery(
  caseId: string,
  body: SimulateRecoveryRequest = {},
): Promise<RecoveryResponse> {
  return request<RecoveryResponse>(
    `/cases/${encodeURIComponent(caseId)}/simulate-recovery`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function selfImprove(caseId: string): Promise<SelfImproveResponse> {
  return request<SelfImproveResponse>(
    `/cases/${encodeURIComponent(caseId)}/self-improve`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Trace
// ---------------------------------------------------------------------------

export function getTrace(caseId: string): Promise<TraceResponse> {
  return request<TraceResponse>(
    `/cases/${encodeURIComponent(caseId)}/trace`,
  );
}

/**
 * Absolute URL for the SSE trace stream. Pass `lastId` to resume from a known
 * event id (mirrors the backend's Last-Event-ID resume support).
 */
export function traceStreamUrl(caseId: string, lastId?: string): string {
  const base = resolveApiBase();
  const url = new URL(
    `${base}/cases/${encodeURIComponent(caseId)}/trace/stream`,
  );
  if (lastId) url.searchParams.set("last_id", lastId);
  return url.toString();
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

export function systemCheck(): Promise<SystemCheckResponse> {
  return request<SystemCheckResponse>("/system-check");
}

/**
 * Redis status snapshot.
 *
 * The backend surfaces Redis health through the trace stream `stream_setup`
 * event (its `redis` field) rather than a dedicated REST route. We derive a
 * stable snapshot from the system-check response, which reports overall service
 * health, and let the live trace stream refine it. This keeps a single source
 * of truth without inventing an endpoint the backend does not serve.
 */
export interface RedisStatsSnapshot {
  status: "configured" | "unconfigured" | "error" | "unknown" | string;
  configured: boolean;
  available: boolean;
  source: "system-check" | "trace-stream";
  raw: Record<string, unknown>;
}

export async function redisStats(): Promise<RedisStatsSnapshot> {
  const check = await systemCheck();
  const ok = check.status === "ok";
  return {
    status: ok ? "configured" : "unknown",
    configured: ok,
    available: ok,
    source: "system-check",
    raw: check as unknown as Record<string, unknown>,
  };
}

export const api = {
  createCase,
  getCase,
  uploadFile,
  extract,
  operate,
  simulateRecovery,
  selfImprove,
  getTrace,
  traceStreamUrl,
  systemCheck,
  redisStats,
  apiOrigin,
};
