// Agent-specific types and stage metadata for the orchestration trace UI.

export type AgentName =
  | 'intake_safety_agent'
  | 'extraction_agent'
  | 'validator_agent'
  | 'state_builder_agent'
  | 'electrophysiology_agent'
  | 'hemodynamics_agent'
  | 'recovery_agent'
  | 'evaluator_agent'

export interface AgentStageInfo {
  name: AgentName
  displayName: string
  stage: number
  parallel?: boolean
  description: string
  icon: string
}

export const AGENT_STAGES = [
  {
    name: 'intake_safety_agent',
    displayName: 'Intake & Safety',
    stage: 1,
    description: 'Validates input safety, creates case record, enforces simulation boundaries',
    icon: 'shield',
  },
  {
    name: 'extraction_agent',
    displayName: 'Multimodal Extraction',
    stage: 2,
    description: 'Extracts structured cardiac observations from PDFs, images, and CSVs',
    icon: 'scan',
  },
  {
    name: 'validator_agent',
    displayName: 'Evidence Validator',
    stage: 3,
    description: 'Validates units, ranges, and resolves data contradictions',
    icon: 'check-circle',
  },
  {
    name: 'state_builder_agent',
    displayName: 'State Builder',
    stage: 4,
    description: 'Builds canonical CardiacTwinState from validated evidence',
    icon: 'layers',
  },
  {
    name: 'electrophysiology_agent',
    displayName: 'Electrophysiology',
    stage: 5,
    parallel: true,
    description: 'Analyzes ECG data and electrical cardiac parameters',
    icon: 'activity',
  },
  {
    name: 'hemodynamics_agent',
    displayName: 'Hemodynamics',
    stage: 5,
    parallel: true,
    description: 'Simulates cardiac cycle, PV loop, and hemodynamic indices',
    icon: 'heart',
  },
  {
    name: 'recovery_agent',
    displayName: 'Recovery Orchestration',
    stage: 6,
    description: 'Generates simulated recovery trajectories and scenario comparisons',
    icon: 'trending-up',
  },
  {
    name: 'evaluator_agent',
    displayName: 'Evaluator & Critic',
    stage: 7,
    description: 'Scores run quality, checks for hallucinations, validates safety',
    icon: 'award',
  },
] satisfies AgentStageInfo[]

export interface PipelineStage {
  stage: number
  agents: AgentStageInfo[]
  status: 'pending' | 'running' | 'success' | 'warning' | 'failed'
  duration_ms?: number
}

export function buildPipelineStages(agentStatuses: Record<string, string>): PipelineStage[] {
  const stages: PipelineStage[] = []
  const stageNums = [...new Set(AGENT_STAGES.map((agent) => agent.stage))].sort()

  for (const stage of stageNums) {
    const agents = AGENT_STAGES.filter((agent) => agent.stage === stage)
    const statuses = agents.map((agent) => agentStatuses[agent.name] || 'pending')

    let status: PipelineStage['status'] = 'pending'
    if (statuses.every((candidate) => candidate === 'success')) status = 'success'
    else if (statuses.includes('failed')) status = 'failed'
    else if (statuses.includes('warning')) status = 'warning'
    else if (statuses.some((candidate) => candidate === 'running' || candidate === 'success')) {
      status = 'running'
    }

    stages.push({ stage, agents, status })
  }

  return stages
}
