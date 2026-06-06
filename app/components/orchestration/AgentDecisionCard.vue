<template>
  <div :class="['agent-card', `agent-card--${response.status}`]">
    <!-- Header -->
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0">
        <!-- Status dot -->
        <div
          :class="['w-2 h-2 rounded-full shrink-0', statusDotClass]"
          :aria-label="`Status: ${response.status}`"
        />
        <span class="text-xs font-mono font-semibold text-white truncate">
          {{ agentInfo?.displayName || response.agent }}
        </span>
        <span v-if="agentInfo?.parallel" class="text-[10px] font-mono shrink-0" style="color:rgba(148,163,184,0.45)">&parallel;</span>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <!-- Confidence bar -->
        <div class="hidden sm:flex items-center gap-1.5">
          <div class="w-14 confidence-bar">
            <div
              class="confidence-fill"
              :class="confidenceBarColor"
              :style="{ width: `${Math.round(response.confidence * 100)}%` }"
            />
          </div>
          <span class="text-[10px] font-mono tabular-nums" style="color:rgba(148,163,184,0.65)">
            {{ Math.round(response.confidence * 100) }}%
          </span>
        </div>
        <!-- Status badge -->
        <span :class="['text-[10px] font-mono px-1.5 py-0.5 rounded', statusBadgeClass]">
          {{ response.status }}
        </span>
      </div>
    </div>

    <!-- Agent description -->
    <p v-if="!compact && agentInfo?.description" class="text-[11px] leading-relaxed mt-1" style="color:rgba(148,163,184,0.6)">
      {{ agentInfo.description }}
    </p>

    <!-- Inputs used -->
    <div v-if="response.inputs_used?.length" class="flex flex-wrap gap-1 mt-1.5">
      <span
        v-for="inp in response.inputs_used.slice(0, compact ? 3 : 5)"
        :key="inp"
        class="text-[10px] font-mono px-1.5 py-0.5 rounded"
        style="background:rgba(16,42,80,0.7); border:1px solid rgba(16,42,80,0.9); color:rgba(148,163,184,0.6);"
      >
        {{ inp }}
      </span>
      <span v-if="response.inputs_used.length > (compact ? 3 : 5)" class="text-[10px] font-mono" style="color:rgba(148,163,184,0.4)">
        +{{ response.inputs_used.length - (compact ? 3 : 5) }}
      </span>
    </div>

    <!-- Key outputs grid -->
    <div v-if="keyOutputs.length" class="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-2">
      <div v-for="[k, v] in keyOutputs" :key="k" class="flex items-center justify-between text-[11px] min-w-0">
        <span class="font-mono truncate" style="color:rgba(148,163,184,0.55)">{{ formatKey(k) }}</span>
        <span class="font-mono font-medium ml-1 shrink-0 text-white/80">{{ formatOutput(v) }}</span>
      </div>
    </div>

    <!-- Warnings -->
    <div v-if="response.warnings?.length" class="mt-2 space-y-1">
      <div
        v-for="w in response.warnings.slice(0, compact ? 1 : 3)"
        :key="w"
        class="inline-warn text-[10px] py-1 px-2"
      >
        <svg class="w-3 h-3 shrink-0 mt-px" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
        </svg>
        {{ w }}
      </div>
      <p v-if="response.warnings.length > (compact ? 1 : 3)" class="text-[10px] font-mono" style="color:rgba(148,163,184,0.45)">
        +{{ response.warnings.length - (compact ? 1 : 3) }} more
      </p>
    </div>

    <!-- Trace steps (expandable) -->
    <div v-if="!compact && response.trace?.length" class="mt-2">
      <button
        class="flex items-center gap-1.5 text-[11px] font-mono transition-colors"
        style="color:rgba(148,163,184,0.5);"
        @click="showTrace = !showTrace"
      >
        <svg
          class="w-3 h-3 transition-transform duration-150"
          :class="showTrace ? 'rotate-90' : ''"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
        Trace ({{ response.trace.length }} step{{ response.trace.length !== 1 ? 's' : '' }})
      </button>
      <div v-if="showTrace" class="mt-2 space-y-1.5 max-h-48 overflow-y-auto">
        <div
          v-for="(step, i) in response.trace"
          :key="i"
          class="p-2 rounded-lg text-[10px] space-y-0.5"
          style="background:rgba(3,13,26,0.6); border:1px solid rgba(16,42,80,0.7);"
        >
          <div class="flex items-center justify-between">
            <span class="font-mono text-cardiac-electric">{{ step.tool }}</span>
            <span class="font-mono" style="color:rgba(148,163,184,0.5)">{{ step.duration_ms.toFixed(0) }}ms</span>
          </div>
          <div v-if="Object.keys(step.inputs).length" class="font-mono truncate" style="color:rgba(148,163,184,0.5)">
            in: {{ formatStepIO(step.inputs) }}
          </div>
          <div v-if="Object.keys(step.outputs).length" class="font-mono truncate" style="color:rgba(148,163,184,0.5)">
            out: {{ formatStepIO(step.outputs) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgentResponse } from '~/types/api'
import { AGENT_STAGES } from '~/types/agents'

const props = defineProps<{
  response: AgentResponse
  expanded?: boolean
  compact?: boolean
}>()

const showTrace = ref(false)
const agentInfo = computed(() => AGENT_STAGES.find((a) => a.name === props.response.agent))

const statusDotClass = computed(() => {
  const s = props.response.status as string
  return {
    'bg-green-400': s === 'success',
    'bg-amber-400': s === 'warning',
    'bg-red-400':   s === 'failed',
    'bg-blue-400 animate-pulse': s === 'running',
    'bg-cardiac-muted/40': !['success','warning','failed','running'].includes(s),
  }
})

const statusBadgeClass = computed(() => {
  const s = props.response.status as string
  if (s === 'success') return 'bg-green-900/40 text-green-400'
  if (s === 'warning') return 'bg-amber-900/40 text-amber-400'
  if (s === 'failed')  return 'bg-red-900/40 text-red-400'
  if (s === 'running') return 'bg-blue-900/40 text-blue-400'
  return 'bg-cardiac-navy-card text-cardiac-muted/50'
})

const confidenceBarColor = computed(() => {
  const c = props.response.confidence
  if (c >= 0.85) return 'bg-green-500'
  if (c >= 0.65) return 'bg-amber-400'
  if (c >= 0.40) return 'bg-orange-400'
  return 'bg-red-500'
})

const DISPLAY_KEYS = [
  'ef_pct', 'cardiac_output_l_min', 'stroke_volume_ml', 'heart_rate_bpm',
  'data_quality_score', 'field_count', 'validated_count', 'scenario_count',
  'overall', 'passed', 'pv_loop_area', 'operating_mode',
]

const keyOutputs = computed(() =>
  Object.entries(props.response.outputs || {})
    .filter(([k]) => DISPLAY_KEYS.includes(k))
    .slice(0, props.compact ? 3 : 6),
)

function formatKey(k: string): string {
  const labels: Record<string, string> = {
    ef_pct: 'EF', cardiac_output_l_min: 'CO', stroke_volume_ml: 'SV',
    heart_rate_bpm: 'HR', data_quality_score: 'Quality', field_count: 'Fields',
    validated_count: 'Validated', scenario_count: 'Scenarios', overall: 'Score',
    passed: 'Passed', pv_loop_area: 'PV area', operating_mode: 'Mode',
  }
  return labels[k] ?? k
}

function formatOutput(val: unknown): string {
  if (typeof val === 'number') return val % 1 === 0 ? String(val) : val.toFixed(2)
  if (typeof val === 'boolean') return val ? 'yes' : 'no'
  if (typeof val === 'string') return val.length > 18 ? val.slice(0, 16) + '…' : val
  if (Array.isArray(val)) return `[${val.length}]`
  return String(val)
}

function formatStepIO(obj: Record<string, unknown>): string {
  return Object.entries(obj)
    .slice(0, 3)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? (v as number).toFixed(1) : String(v).slice(0, 8)}`)
    .join(' ')
}
</script>

<style scoped>
.agent-card {
  padding: 0.7rem 0.8rem;
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.88), rgba(7, 17, 31, 0.72));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 14px 42px rgba(0, 0, 0, 0.22);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.agent-card--success {
  border-color: rgba(34, 197, 94, 0.26);
}

.agent-card--warning {
  border-color: rgba(245, 158, 11, 0.34);
}

.agent-card--failed {
  border-color: rgba(239, 68, 68, 0.36);
}

.agent-card--running {
  border-color: rgba(56, 189, 248, 0.40);
  box-shadow: var(--ht-shadow-glow-blue);
}

.confidence-bar {
  height: 0.25rem;
  overflow: hidden;
  background: rgba(30, 41, 59, 0.88);
  border-radius: 999px;
}

.confidence-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 500ms ease;
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

@media (prefers-reduced-motion: reduce) {
  .agent-card,
  .confidence-fill {
    transition: none;
  }
}
</style>
