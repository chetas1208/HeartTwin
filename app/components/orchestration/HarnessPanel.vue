<template>
  <div class="grid lg:grid-cols-3 gap-3 text-xs font-mono">
    <section class="glass-card p-3 lg:col-span-2">
      <div class="flex items-center justify-between gap-2 mb-2">
        <h3 class="panel-label">Agent Pipeline</h3>
        <span class="sim-label text-[9px]">8 agents</span>
      </div>
      <div class="grid sm:grid-cols-2 gap-2">
        <div
          v-for="(agent, index) in AGENT_STAGES"
          :key="agent.name"
          class="rounded-lg px-3 py-2"
          style="background:rgba(7,20,40,0.72); border:1px solid rgba(16,42,80,0.65);"
        >
          <div class="flex items-center gap-2">
            <span class="text-[10px] w-4" style="color:rgba(148,163,184,0.45)">{{ index + 1 }}.</span>
            <span class="font-semibold text-white truncate">{{ agent.displayName }}</span>
            <span class="ml-auto text-[10px]" :class="statusClass(responseFor(agent.name)?.status)">
              {{ responseFor(agent.name)?.status ?? 'pending' }}
            </span>
          </div>
          <div class="mt-1 grid grid-cols-2 gap-x-2 gap-y-1" style="color:rgba(148,163,184,0.55)">
            <span>Inputs</span>
            <span class="truncate text-right">{{ inputsFor(agent.name) }}</span>
            <span>Tools</span>
            <span class="truncate text-right">{{ toolsFor(agent.name) }}</span>
            <span>Confidence</span>
            <span class="text-right">{{ confidenceFor(agent.name) }}</span>
          </div>
          <a
            v-if="weave?.run_url"
            :href="weave.run_url"
            target="_blank"
            rel="noreferrer"
            class="inline-block mt-1 text-[10px]"
            style="color:rgba(0,212,255,0.75)"
          >
            Trace link
          </a>
          <p
            v-if="responseFor(agent.name)?.warnings?.length"
            class="mt-1 text-[10px] truncate"
            style="color:rgba(251,191,36,0.85)"
          >
            {{ responseFor(agent.name)?.warnings?.[0] }}
          </p>
        </div>
      </div>
    </section>

    <section class="glass-card p-3">
      <h3 class="panel-label mb-2">Weave Trace</h3>
      <div class="space-y-1.5">
        <InfoRow label="Weave status" :value="weaveStatusLabel" :class-name="weaveStatusClass" />
        <InfoRow label="Project" :value="weave?.project || 'hearttwin-lab'" />
        <InfoRow label="Latest run ID" :value="weave?.latest_run_id || weave?.run_id || 'local only'" />
        <InfoRow label="Traced stages" :value="String(tracedStagesCount)" />
        <InfoRow label="Tool calls" :value="String(tracedToolCallsCount)" />
      </div>
      <a
        v-if="weaveProjectUrl"
        :href="weaveProjectUrl"
        target="_blank"
        rel="noreferrer"
        class="inline-block mt-2 text-[10px]"
        style="color:rgba(0,212,255,0.8)"
      >
        View Weave Project
      </a>
      <p v-else class="mt-2 text-[10px] leading-relaxed" style="color:rgba(148,163,184,0.55)">
        Weave is not configured. Local JSON traces are still active.
      </p>
      <ul v-if="weaveWarnings.length" class="mt-2 space-y-1">
        <li v-for="warning in weaveWarnings" :key="warning" class="inline-warn text-[10px] py-1">
          {{ warning }}
        </li>
      </ul>
    </section>

    <section class="glass-card p-3">
      <h3 class="panel-label mb-2">Eval Scores</h3>
      <table class="w-full text-[11px]">
        <tbody>
          <tr v-for="row in scoreRows" :key="row.key" style="border-bottom:1px solid rgba(16,42,80,0.45)">
            <td class="py-1.5 pr-2" style="color:rgba(148,163,184,0.65)">{{ row.label }}</td>
            <td class="py-1.5 text-right tabular-nums" :class="scoreClass(row.value, row.risk)">
              {{ formatScore(row.value) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p class="mt-2 text-[10px]" style="color:rgba(123,184,255,0.75)">Hallucination risk: lower is better.</p>
    </section>

    <section class="glass-card p-3">
      <div class="flex items-center justify-between gap-2 mb-2">
        <h3 class="panel-label">Self-Improvement Run</h3>
        <button
          class="action-btn action-btn--ready text-[10px] py-1.5 px-2 w-auto"
          :disabled="!hasRecovery || loading"
          :title="!hasRecovery ? 'Run recovery simulation first' : undefined"
          @click="$emit('improve')"
        >
          Improve Harness Run
        </button>
      </div>
      <div v-if="selfImprovement" class="space-y-2">
        <div class="grid grid-cols-3 gap-2">
          <MetricMini label="Before" :value="selfImprovement.before?.eval_scores?.overall_score" />
          <MetricMini label="After" :value="selfImprovement.after?.eval_scores?.overall_score" />
          <MetricMini label="Delta" :value="selfImprovement.score_delta?.overall_score" signed />
        </div>
        <div>
          <p class="text-[10px] uppercase tracking-widest mb-1" style="color:rgba(148,163,184,0.45)">Critic findings</p>
          <p class="leading-relaxed" style="color:rgba(148,163,184,0.72)">
            {{ selfImprovement.critic_findings?.[0]?.issue || 'No rerun findings yet' }}
          </p>
        </div>
        <div>
          <p class="text-[10px] uppercase tracking-widest mb-1" style="color:rgba(148,163,184,0.45)">Improvement plan</p>
          <ul class="space-y-1">
            <li v-for="item in selfImprovement.improvement_plan?.slice(0, 3)" :key="item.change" style="color:rgba(148,163,184,0.72)">
              {{ item.change }}
            </li>
          </ul>
        </div>
        <p class="text-[10px]" style="color:rgba(74,222,128,0.78)">Warnings preserved: {{ selfImprovement.after?.warnings?.length ?? 0 }}</p>
      </div>
      <p v-else class="leading-relaxed" style="color:rgba(148,163,184,0.58)">
        Run a bounded recovery simulation, then compare before and after eval scores for the harness.
      </p>
    </section>

    <section class="glass-card p-3">
      <h3 class="panel-label mb-2">Safety Critic</h3>
      <div class="space-y-1.5">
        <InfoRow label="Safety compliance" :value="formatScore(evalScores?.safety_compliance)" :class-name="scoreClass(evalScores?.safety_compliance)" />
        <InfoRow label="Hallucination risk" :value="formatScore(evalScores?.hallucination_risk)" :class-name="scoreClass(evalScores?.hallucination_risk, true)" />
        <InfoRow label="Failed checks" :value="String(evalScores?.failed_checks?.length ?? 0)" />
      </div>
      <ul v-if="evalScores?.warnings?.length" class="mt-2 space-y-1">
        <li v-for="warning in evalScores.warnings.slice(0, 3)" :key="warning" class="inline-warn text-[10px] py-1">
          {{ warning }}
        </li>
      </ul>
    </section>

    <section class="glass-card p-3 lg:col-span-3">
      <h3 class="panel-label mb-2">Submission Summary</h3>
      <div class="grid md:grid-cols-2 gap-3 leading-relaxed" style="color:rgba(148,163,184,0.72)">
        <p>
          HeartTwin Lab is an agentic cardiac digital twin simulator that converts cardiac reports, ECG-style data,
          imaging inputs, and manual vitals into a simplified, explainable heart operation model. Specialized agents
          extract evidence, validate values, build a canonical cardiac state, run deterministic hemodynamics simulations,
          generate bounded recovery scenarios, and evaluate plausibility and safety using Weave traces and evals.
        </p>
        <p>
          It is useful as an educational and research-oriented cardiac simulation environment, not for diagnosis or
          treatment decisions. HeartTwin shows how multi-agent systems can coordinate around deterministic scientific
          tools instead of hallucinating medical claims.
        </p>
      </div>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 mt-3">
        <InfoPill title="W&B Weave" text="Agent traces, tool traces, eval scoring, run comparison, and rerun inspection." />
        <InfoPill title="OpenAI" text="Optional structured extraction and critic summaries; numeric simulation is deterministic Python." />
        <InfoPill title="Redis" text="Optional case memory, trace cache, validated evidence, and scenario history." />
        <InfoPill title="Cursor" text="AI development environment; no coding tool is added as a GitHub contributor." />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h } from 'vue'
import type { AgentResponse, EvaluationReport, SelfImproveResponse, WeaveInfo } from '~/types/api'
import { AGENT_STAGES, type AgentName } from '~/types/agents'

const props = defineProps<{
  responses: AgentResponse[]
  evaluation?: EvaluationReport | null
  weave?: WeaveInfo | null
  traces?: Array<Record<string, unknown>>
  hasRecovery: boolean
  selfImprovement?: SelfImproveResponse | null
  loading?: boolean
}>()

defineEmits<{ improve: [] }>()

const responseMap = computed(() => {
  const map: Partial<Record<AgentName, AgentResponse>> = {}
  for (const response of props.responses) map[response.agent as AgentName] = response
  return map
})

const evalScores = computed(() => props.evaluation?.eval_scores ?? null)
const weaveProjectUrl = computed(() => props.weave?.project_url || null)
const weaveWarnings = computed(() => props.weave?.warnings ?? [])
const tracedStagesCount = computed(() =>
  props.weave?.traced_stages_count
  ?? props.traces?.filter(t => t.kind === 'agent_stage').length
  ?? props.responses.length,
)
const tracedToolCallsCount = computed(() =>
  props.weave?.traced_tool_calls_count
  ?? props.traces?.filter(t => t.kind === 'tool_call').length
  ?? props.responses.reduce((count, response) => count + response.trace.length, 0),
)

const weaveStatusLabel = computed(() => {
  if (props.weave?.status === 'connected' || props.weave?.enabled) return 'Connected'
  if (props.weave?.status === 'error') return 'Error'
  return 'Not configured'
})
const weaveStatusClass = computed(() => {
  if (weaveStatusLabel.value === 'Connected') return 'text-green-400'
  if (weaveStatusLabel.value === 'Error') return 'text-red-400'
  return 'text-amber-400'
})

const scoreRows = computed(() => [
  { key: 'extraction_completeness', label: 'Extraction completeness', value: evalScores.value?.extraction_completeness },
  { key: 'physiological_plausibility', label: 'Physiological plausibility', value: evalScores.value?.physiological_plausibility },
  { key: 'safety_compliance', label: 'Safety compliance', value: evalScores.value?.safety_compliance },
  { key: 'hallucination_risk', label: 'Hallucination risk', value: evalScores.value?.hallucination_risk, risk: true },
  { key: 'visualization_readiness', label: 'Visualization readiness', value: evalScores.value?.visualization_readiness },
  { key: 'recovery_scenario_stability', label: 'Recovery scenario stability', value: evalScores.value?.recovery_scenario_stability },
  { key: 'overall_score', label: 'Overall score', value: evalScores.value?.overall_score },
])

function responseFor(agent: AgentName) {
  return responseMap.value[agent]
}

function inputsFor(agent: AgentName) {
  const inputs = responseFor(agent)?.inputs_used ?? []
  return inputs.length ? inputs.slice(0, 2).join(', ') : 'pending'
}

function toolsFor(agent: AgentName) {
  const tools = responseFor(agent)?.trace?.map(t => t.tool) ?? []
  return tools.length ? tools.slice(0, 2).join(', ') : 'pending'
}

function confidenceFor(agent: AgentName) {
  const value = responseFor(agent)?.confidence
  return value == null ? 'pending' : `${Math.round(value * 100)}%`
}

function formatScore(value?: number | null) {
  if (value == null) return '—'
  return `${Math.round(value * 100)}%`
}

function statusClass(status?: string) {
  if (status === 'success') return 'text-green-400'
  if (status === 'warning') return 'text-amber-400'
  if (status === 'failed') return 'text-red-400'
  return 'text-cardiac-muted/50'
}

function scoreClass(value?: number | null, risk = false) {
  if (value == null) return 'text-cardiac-muted/50'
  const strong = risk ? value <= 0.25 : value >= 0.75
  const warn = risk ? value <= 0.50 : value >= 0.50
  if (strong) return 'text-green-400'
  if (warn) return 'text-amber-400'
  return 'text-red-400'
}

const InfoRow = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: String, required: true },
    className: { type: String, default: 'text-white' },
  },
  setup(rowProps) {
    return () => h('div', { class: 'flex items-center justify-between gap-2' }, [
      h('span', { style: 'color:rgba(148,163,184,0.55)' }, rowProps.label),
      h('span', { class: ['text-right tabular-nums truncate', rowProps.className] }, rowProps.value),
    ])
  },
})

const MetricMini = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: Number, default: null },
    signed: { type: Boolean, default: false },
  },
  setup(metricProps) {
    return () => h('div', { class: 'rounded-lg px-2 py-2', style: 'background:rgba(10,31,58,0.55); border:1px solid rgba(16,42,80,0.55);' }, [
      h('p', { class: 'text-[10px]', style: 'color:rgba(148,163,184,0.5)' }, metricProps.label),
      h('p', { class: 'text-sm text-white font-semibold tabular-nums' },
        metricProps.value == null
          ? '—'
          : `${metricProps.signed && metricProps.value > 0 ? '+' : ''}${Math.round(metricProps.value * 100)}%`),
    ])
  },
})

const InfoPill = defineComponent({
  props: {
    title: { type: String, required: true },
    text: { type: String, required: true },
  },
  setup(pillProps) {
    return () => h('div', { class: 'rounded-lg px-3 py-2', style: 'background:rgba(10,31,58,0.55); border:1px solid rgba(16,42,80,0.55);' }, [
      h('p', { class: 'text-[11px] font-semibold text-white' }, pillProps.title),
      h('p', { class: 'text-[10px] mt-1 leading-relaxed', style: 'color:rgba(148,163,184,0.62)' }, pillProps.text),
    ])
  },
})
</script>

<style scoped>
.glass-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.88), rgba(7, 17, 31, 0.72));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.24);
}

.panel-label {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.sim-label {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem 0.5rem;
  color: var(--ht-cyan);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.26);
  border-radius: 999px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  color: var(--ht-text);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-weight: 700;
  background: rgba(10, 20, 35, 0.76);
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-sm);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.action-btn:not(:disabled):hover {
  border-color: rgba(56, 189, 248, 0.40);
  box-shadow: var(--ht-shadow-glow-blue);
  transform: translateY(-1px);
}

.action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.inline-warn {
  display: flex;
  align-items: flex-start;
  gap: 0.35rem;
  color: rgba(251, 191, 36, 0.92);
  background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.20);
  border-radius: var(--ht-radius-sm);
}

table {
  border-collapse: collapse;
}

@media (prefers-reduced-motion: reduce) {
  .action-btn {
    transition: none;
  }

  .action-btn:not(:disabled):hover {
    transform: none;
  }
}
</style>
