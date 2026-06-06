import { defineStore } from 'pinia'
import type { AgentResponse, EvaluationReport, ExtractRequest, SelfImproveResponse, UploadedFile, WeaveInfo } from '~/types/api'
import type {
  CardiacTwinState,
  OperatingEnvironment,
  RecoveryConfig,
  RecoveryScenario,
  SimulationVisualization,
} from '~/types/heart'
import { useHeartTwinApi } from '~/composables/useHeartTwinApi'

export const useCaseStore = defineStore('case', {
  state: () => ({
    caseId: null as string | null,
    files: [] as UploadedFile[],
    validatedFields: {} as Record<string, unknown>,
    state: null as CardiacTwinState | null,
    simulationResult: null as SimulationVisualization | null,
    recoveryScenarios: [] as RecoveryScenario[],
    stageResults: [] as AgentResponse[],
    evaluationReport: null as EvaluationReport | null,
    weaveInfo: null as WeaveInfo | null,
    traceEvents: [] as Array<Record<string, unknown>>,
    selfImprovementResult: null as SelfImproveResponse | null,
    dataQualityScore: null as number | null,
    currentStage: '' as string,
    loading: false,
    error: null as string | null,
    agentStatuses: {} as Record<string, string>,
  }),

  getters: {
    hasState: (s) => !!s.state,
    hasExtracted: (s) => Object.keys(s.validatedFields).length > 0 || !!s.state,
    hasSimulation: (s) => !!s.simulationResult,
    hasRecovery: (s) => s.recoveryScenarios.length > 0,
    warnings: (s): string[] => [
      ...(s.state?.warnings ?? []),
      ...(s.evaluationReport?.warnings ?? []),
    ],
  },

  actions: {
    async createCase(notes?: string) {
      const api = useHeartTwinApi()
      this._setLoading('Creating case')
      try {
        const res = await api.createCase({ patient_notes: notes })
        this.caseId = res.case_id
        this.error = null
      } catch (e) {
        this.error = String(e)
        throw e
      } finally {
        this._clearLoading()
      }
    },

    addFile(file: UploadedFile) {
      this.files.push(file)
    },

    async extract(fileIds: string[] = [], userVitals: Record<string, unknown> = {}) {
      if (!this.caseId) throw new Error('No case ID')
      const api = useHeartTwinApi()
      this._setLoading('Extracting evidence (stages 1-3)')
      try {
        const res = await api.extract(this.caseId, {
          file_ids: fileIds,
          user_vitals: Object.keys(userVitals).length ? userVitals : undefined,
        } as ExtractRequest)
        this.validatedFields = res.validated_fields ?? {}
        if (res.weave) this.weaveInfo = res.weave
        this._appendStageResults(res.stage_results ?? [])
        await this.refreshTrace()
        this.error = null
      } catch (e) {
        this.error = String(e)
        throw e
      } finally {
        this._clearLoading()
      }
    },

    async operate(env?: Partial<OperatingEnvironment>) {
      if (!this.caseId) throw new Error('No case ID')
      const api = useHeartTwinApi()
      this._setLoading('Building cardiac state and simulating (stages 4-5-7)')
      try {
        const res = await api.operate(this.caseId, { operating_environment: env })
        if (res.state) this.state = res.state
        if (res.visualization) this.simulationResult = res.visualization
        if (res.evaluation) this.evaluationReport = res.evaluation
        if (res.weave) this.weaveInfo = res.weave
        this.dataQualityScore = res.data_quality_score ?? null
        this._appendStageResults(res.stage_results ?? [])
        await this.refreshTrace()
        this.error = null
      } catch (e) {
        this.error = String(e)
        throw e
      } finally {
        this._clearLoading()
      }
    },

    async simulateRecovery(config?: RecoveryConfig) {
      if (!this.caseId) throw new Error('No case ID')
      const api = useHeartTwinApi()
      this._setLoading('Generating recovery scenarios (stages 6-7)')
      try {
        const res = await api.simulateRecovery(this.caseId, { recovery_config: config })
        this.recoveryScenarios = res.scenarios ?? []
        if (res.evaluation) this.evaluationReport = res.evaluation
        if (res.weave) this.weaveInfo = res.weave
        this._appendStageResults(res.stage_results ?? [])
        await this.refreshTrace()
        this.error = null
      } catch (e) {
        this.error = String(e)
        throw e
      } finally {
        this._clearLoading()
      }
    },

    async improveHarnessRun() {
      if (!this.caseId) throw new Error('No case ID')
      const api = useHeartTwinApi()
      this._setLoading('Improving harness run')
      try {
        const res = await api.selfImprove(this.caseId)
        this.selfImprovementResult = res
        if (res.after?.eval_scores && Object.keys(res.after.eval_scores).length) {
          this.evaluationReport = {
            ...(this.evaluationReport ?? {
              scores: {
                data_completeness: 0,
                physiological_plausibility: 0,
                hallucination_risk: 0,
                safety_compliance: 0,
                visualization_readiness: 0,
                overall: 0,
              },
              passed: false,
              force_revision_issues: [],
              prior_field_count: 0,
              prior_fields: [],
              warnings: [],
              agent_statuses: {},
              simulation_note: '',
            }),
            eval_scores: res.after.eval_scores as NonNullable<EvaluationReport['eval_scores']>,
          }
        }
        if (res.weave) this.weaveInfo = res.weave
        if (res.trace) this.traceEvents = res.trace
        const latest = await api.getCase(this.caseId)
        this.recoveryScenarios = latest.recovery_scenarios ?? this.recoveryScenarios
        this.stageResults = latest.stage_results ?? this.stageResults
        this.state = latest.state ?? this.state
        this.error = null
      } catch (e) {
        this.error = String(e)
        throw e
      } finally {
        this._clearLoading()
      }
    },

    async refreshTrace() {
      if (!this.caseId) return
      const api = useHeartTwinApi()
      const res = await api.getTrace(this.caseId)
      this.traceEvents = res.traces ?? []
      if (res.weave) this.weaveInfo = res.weave
    },

    reset() {
      this.caseId = null
      this.files = []
      this.validatedFields = {}
      this.state = null
      this.simulationResult = null
      this.recoveryScenarios = []
      this.stageResults = []
      this.evaluationReport = null
      this.weaveInfo = null
      this.traceEvents = []
      this.selfImprovementResult = null
      this.dataQualityScore = null
      this.currentStage = ''
      this.loading = false
      this.error = null
      this.agentStatuses = {}
    },

    _setLoading(stage: string) {
      this.loading = true
      this.currentStage = stage
      this.error = null
    },

    _clearLoading() {
      this.loading = false
      this.currentStage = ''
    },

    _appendStageResults(results: AgentResponse[]) {
      this.stageResults.push(...results)
      for (const r of results) {
        this.agentStatuses[r.agent] = r.status
      }
    },
  },
})
