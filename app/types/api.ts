import type { CardiacTwinState, RecoveryConfig, RecoveryScenario, SimulationConfig, SimulationVisualization } from './heart'

export interface UploadedFile {
  file_id: string
  filename: string
  content_type: string
  size_bytes: number
  storage_url?: string | null
  uploaded_at: string
}

export interface CaseRecord {
  case_id: string
  created_at: string
  updated_at: string
  files: UploadedFile[]
  patient_notes?: string | null
  state?: CardiacTwinState | null
  stage_results: AgentResponse[]
  simulation_result?: SimulationVisualization | null
  recovery_scenarios?: RecoveryScenario[] | null
  validated_fields?: Record<string, unknown>
  status: string
  safety_disclaimer: string
}

export interface CreateCaseRequest {
  patient_notes?: string
  simulation_config?: SimulationConfig
}

export interface ExtractRequest {
  file_ids: string[]
  user_vitals?: Record<string, number | string | null>
}

export interface OperateRequest {
  operating_environment?: Partial<import('./heart').OperatingEnvironment>
}

export interface SimulateRecoveryRequest {
  recovery_config?: RecoveryConfig
  scenarios?: RecoveryConfig[]
}

export interface HealthResponse {
  status: string
  service: string
  disclaimer?: string
  environment?: Record<string, unknown>
}

export interface ApiError {
  error: string
  detail: string
  safety_disclaimer?: string
}

export type AgentStatus = 'success' | 'warning' | 'failed'

export interface AgentTraceStep {
  tool: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  duration_ms: number
}

export interface AgentResponse {
  agent: string
  status: AgentStatus
  inputs_used: string[]
  outputs: Record<string, unknown>
  warnings: string[]
  confidence: number
  trace: AgentTraceStep[]
}

export interface EvalScores {
  extraction_completeness: number
  physiological_plausibility: number
  safety_compliance: number
  hallucination_risk: number
  visualization_readiness: number
  recovery_scenario_stability: number
  overall_score: number
  warnings: string[]
  failed_checks: string[]
}

export interface WeaveInfo {
  enabled: boolean
  status: 'connected' | 'not_configured' | 'error' | string
  project: string
  project_url?: string | null
  run_id?: string | null
  latest_run_id?: string | null
  run_url?: string | null
  traced_stages_count?: number
  traced_tool_calls_count?: number
  warnings: string[]
}

export interface EvaluationReport {
  scores: {
    data_completeness: number
    extraction_completeness?: number
    physiological_plausibility: number
    hallucination_risk: number
    safety_compliance: number
    visualization_readiness: number
    recovery_scenario_stability?: number
    overall: number
    overall_score?: number
  }
  eval_scores?: EvalScores
  passed: boolean
  force_revision_issues: string[]
  failed_checks?: string[]
  prior_field_count: number
  prior_fields: string[]
  warnings: string[]
  agent_statuses: Record<string, AgentStatus>
  simulation_note: string
}

export interface ExtractResponse {
  case_id: string
  status: string
  data_quality_score: number
  state: CardiacTwinState | null
  stage_results: AgentResponse[]
  safety_disclaimer: string
  validated_fields: Record<string, unknown>
  validated_field_count: number
  weave?: WeaveInfo
}

export interface OperateResponse {
  case_id: string
  status: string
  state: CardiacTwinState | null
  data_quality_score: number
  visualization: SimulationVisualization | null
  evaluation: EvaluationReport
  stage_results: AgentResponse[]
  safety_disclaimer: string
  weave?: WeaveInfo
}

export interface RecoveryResponse {
  case_id: string
  status: string
  scenarios: RecoveryScenario[]
  evaluation?: EvaluationReport
  stage_results: AgentResponse[]
  simulation_note: string
  safety_disclaimer: string
  weave?: WeaveInfo
}

export interface SelfImproveResponse {
  case_id: string
  status: 'success' | 'warning' | 'failed'
  before: {
    eval_scores: Partial<EvalScores>
    recovery_summary: Record<string, unknown>
    warnings: string[]
  }
  critic_findings: Array<{
    issue: string
    severity: 'low' | 'medium' | 'high'
    evidence: string
    fix: string
  }>
  improvement_plan: Array<{
    change: string
    reason: string
    bounded: boolean
  }>
  after: {
    eval_scores: Partial<EvalScores>
    recovery_summary: Record<string, unknown>
    warnings: string[]
  }
  score_delta: {
    overall_score: number
    physiological_plausibility: number
    safety_compliance: number
    hallucination_risk: number
  }
  trace: Array<Record<string, unknown>>
  weave: WeaveInfo
  safety_disclaimer: string
}
