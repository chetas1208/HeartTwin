/*
 * Global app state for HeartTwin Lab (Zustand).
 *
 * Single source of truth shared by every panel. Components READ slices of this
 * store and call actions; they never call the API client directly for pipeline
 * orchestration (use runPipeline). Trace events are appended by the
 * useTraceStream hook. Everything is typed against web/types/*.
 *
 * Sibling agents: add a derived selector or a narrowly-scoped action here only
 * if your panel genuinely needs new shared state. Do not stash component-local
 * UI state in this store.
 */

import { create } from "zustand";
import type {
  AgentResponse,
  EvaluationReport,
  WeaveInfo,
} from "@/types/api";
import type {
  CardiacTwinState,
  OperatingEnvironment,
  RecoveryConfig,
  RecoveryScenario,
  SimulationVisualization,
} from "@/types/heart";
import {
  createCase,
  extract,
  operate,
  simulateRecovery,
  ApiRequestError,
} from "@/lib/api";
import type { RedisStatsSnapshot } from "@/lib/api";

/** High-level lifecycle of the active case as the user / pipeline progresses. */
export type PipelineStatus =
  | "idle"
  | "creating"
  | "created"
  | "extracting"
  | "extracted"
  | "operating"
  | "operated"
  | "simulating"
  | "complete"
  | "improving"
  | "error";

/** One normalized trace event appended from the SSE stream. */
export interface TraceEvent {
  /** Server event id (Redis stream id or local-N). Used for resume. */
  id: string;
  /** Event name / kind reported by the stream (agent_stage, tool_call, ...). */
  kind: string;
  /** Wall-clock time the client received the event. */
  receivedAt: number;
  /** Raw decoded SSE payload. */
  payload: Record<string, unknown>;
}

export interface StreamMeta {
  source: "redis" | "local" | "unknown";
  connected: boolean;
  lastEventId: string | null;
  error: string | null;
}

interface HeartTwinState {
  // ---- identity / lifecycle ----
  caseId: string | null;
  status: PipelineStatus;
  error: string | null;
  safetyDisclaimer: string | null;

  // ---- pipeline results ----
  validatedFields: Record<string, unknown>;
  validatedFieldCount: number;
  state: CardiacTwinState | null;
  visualization: SimulationVisualization | null;
  evaluation: EvaluationReport | null;
  scenarios: RecoveryScenario[];
  stageResults: AgentResponse[];

  // ---- observability ----
  traceEvents: TraceEvent[];
  stream: StreamMeta;
  weave: WeaveInfo | null;
  redisStats: RedisStatsSnapshot | null;

  // ---- setters (used by components / hooks) ----
  setCaseId: (caseId: string | null) => void;
  setStatus: (status: PipelineStatus) => void;
  setError: (error: string | null) => void;
  setState: (state: CardiacTwinState | null) => void;
  setVisualization: (viz: SimulationVisualization | null) => void;
  setEvaluation: (evaluation: EvaluationReport | null) => void;
  setScenarios: (scenarios: RecoveryScenario[]) => void;
  setWeave: (weave: WeaveInfo | null) => void;
  setRedisStats: (stats: RedisStatsSnapshot | null) => void;

  // ---- trace stream wiring (called by useTraceStream) ----
  appendTraceEvent: (event: TraceEvent) => void;
  setStreamMeta: (meta: Partial<StreamMeta>) => void;
  clearTrace: () => void;

  // ---- orchestration ----
  runPipeline: (options?: RunPipelineOptions) => Promise<void>;
  reset: () => void;
}

export interface RunPipelineOptions {
  /** Vitals passed to /extract (manual input path, no files required). */
  userVitals?: Record<string, number | string | null>;
  /** File ids to extract from; empty/omitted extracts from all case files. */
  fileIds?: string[];
  /** Patient notes for the new case. */
  patientNotes?: string;
  /** Operating environment override for /operate. */
  operatingEnvironment?: Partial<OperatingEnvironment>;
  /** Recovery config override for /simulate-recovery. */
  recoveryConfig?: RecoveryConfig;
  /** Reuse an existing case instead of creating a new one. */
  caseId?: string;
}

const initialStream: StreamMeta = {
  source: "unknown",
  connected: false,
  lastEventId: null,
  error: null,
};

const initialState = {
  caseId: null,
  status: "idle" as PipelineStatus,
  error: null,
  safetyDisclaimer: null,
  validatedFields: {} as Record<string, unknown>,
  validatedFieldCount: 0,
  state: null,
  visualization: null,
  evaluation: null,
  scenarios: [] as RecoveryScenario[],
  stageResults: [] as AgentResponse[],
  traceEvents: [] as TraceEvent[],
  stream: initialStream,
  weave: null,
  redisStats: null,
};

/** Keep the in-memory trace log bounded so a long run never leaks memory. */
const MAX_TRACE_EVENTS = 500;

export const useHeartTwinStore = create<HeartTwinState>((set, get) => ({
  ...initialState,

  setCaseId: (caseId) => set({ caseId }),
  setStatus: (status) => set({ status }),
  setError: (error) => set({ error }),
  setState: (state) => set({ state }),
  setVisualization: (visualization) => set({ visualization }),
  setEvaluation: (evaluation) => set({ evaluation }),
  setScenarios: (scenarios) => set({ scenarios }),
  setWeave: (weave) => set({ weave }),
  setRedisStats: (redisStats) => set({ redisStats }),

  appendTraceEvent: (event) =>
    set((s) => {
      const next = [...s.traceEvents, event];
      return {
        traceEvents:
          next.length > MAX_TRACE_EVENTS
            ? next.slice(next.length - MAX_TRACE_EVENTS)
            : next,
        stream: { ...s.stream, lastEventId: event.id },
      };
    }),

  setStreamMeta: (meta) =>
    set((s) => ({ stream: { ...s.stream, ...meta } })),

  clearTrace: () =>
    set({ traceEvents: [], stream: initialStream }),

  runPipeline: async (options = {}) => {
    const { setStatus, setWeave } = get();
    set({ error: null });

    try {
      // 1. Create (or reuse) the case.
      let caseId = options.caseId ?? null;
      if (!caseId) {
        setStatus("creating");
        const created = await createCase({
          patient_notes: options.patientNotes ?? null,
        });
        caseId = created.case_id;
        set({
          caseId,
          safetyDisclaimer: created.safety_disclaimer,
        });
        if (created.weave) setWeave(created.weave);
      } else {
        set({ caseId });
      }
      set({ status: "created" });

      // 2. Extract (stages 1-3): validate evidence.
      setStatus("extracting");
      const extracted = await extract(caseId, {
        file_ids: options.fileIds ?? [],
        user_vitals: options.userVitals,
      });
      set({
        validatedFields: extracted.validated_fields,
        validatedFieldCount: extracted.validated_field_count,
        state: extracted.state ?? get().state,
        stageResults: extracted.stage_results,
        safetyDisclaimer: extracted.safety_disclaimer,
        status: "extracted",
      });
      if (extracted.weave) setWeave(extracted.weave);

      // 3. Operate (stages 4-5-7): build state, simulate cycle, evaluate.
      setStatus("operating");
      const operated = await operate(caseId, {
        operating_environment: options.operatingEnvironment ?? null,
      });
      set({
        state: operated.state,
        visualization: operated.visualization,
        evaluation: operated.evaluation,
        stageResults: operated.stage_results,
        safetyDisclaimer: operated.safety_disclaimer,
        status: "operated",
      });
      if (operated.weave) setWeave(operated.weave);

      // 4. Simulate recovery (stages 6-7): bounded scenarios.
      setStatus("simulating");
      const recovery = await simulateRecovery(caseId, {
        recovery_config: options.recoveryConfig ?? null,
      });
      set({
        scenarios: recovery.scenarios,
        evaluation: recovery.evaluation ?? get().evaluation,
        stageResults: recovery.stage_results,
        safetyDisclaimer: recovery.safety_disclaimer,
        status: "complete",
      });
      if (recovery.weave) setWeave(recovery.weave);
    } catch (cause) {
      const message =
        cause instanceof ApiRequestError
          ? cause.detail
          : cause instanceof Error
            ? cause.message
            : "Pipeline failed";
      set({ status: "error", error: message });
      throw cause;
    }
  },

  reset: () => set({ ...initialState }),
}));
