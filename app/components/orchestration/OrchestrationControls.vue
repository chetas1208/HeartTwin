<template>
  <div class="space-y-4">
    <!-- Pipeline step status -->
    <div>
      <p class="section-title">Pipeline</p>
      <div class="space-y-1">
        <div
          v-for="step in pipelineSteps"
          :key="step.n"
          class="flex items-center gap-2 py-1"
        >
          <span
            class="w-5 h-5 rounded-full text-xs font-mono font-bold flex items-center justify-center shrink-0"
            :class="step.statusClass"
          >{{ step.n }}</span>
          <span class="text-xs font-mono flex-1" :class="step.labelClass">{{ step.label }}</span>
          <span class="text-xs font-mono px-1.5 py-0.5 rounded" :class="step.badgeClass">
            {{ step.badge }}
          </span>
        </div>
      </div>
    </div>

    <!-- Run buttons -->
    <div class="space-y-2">
      <button
        :disabled="disabled || loading"
        class="w-full btn-primary text-sm flex items-center justify-center gap-2"
        @click="emit('extract')"
      >
        <svg v-if="loading && stage?.includes('1-3')" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span>{{ loading && stage?.includes('1-3') ? 'Extracting evidence…' : 'Extract Evidence' }}</span>
      </button>

      <button
        :disabled="disabled || !hasState || loading"
        class="w-full btn-secondary text-sm flex items-center justify-center gap-2"
        @click="emit('operate')"
      >
        <svg v-if="loading && stage?.includes('4-5')" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span>{{ loading && stage?.includes('4-5') ? 'Simulating…' : 'Build State & Operate' }}</span>
      </button>

      <button
        :disabled="disabled || !hasState || loading"
        class="w-full btn-secondary text-sm flex items-center justify-center gap-2"
        @click="emit('simulate-recovery')"
      >
        <svg v-if="loading && stage?.includes('6-7')" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span>{{ loading && stage?.includes('6-7') ? 'Computing scenarios…' : 'Simulate Recovery' }}</span>
      </button>
    </div>

    <!-- Visualization toggles -->
    <div>
      <p class="section-title">Visualization</p>
      <div class="space-y-2">
        <label v-for="toggle in TOGGLES" :key="toggle.key" class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            :checked="simStore[toggle.key]"
            class="accent-cardiac-red"
            @change="(e) => simStore[toggle.key] = (e.target as HTMLInputElement).checked"
          >
          <span class="text-xs text-cardiac-muted">{{ toggle.label }}</span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSimulationStore } from '~/stores/simulation'
import { useCaseStore } from '~/stores/case'

const simStore = useSimulationStore()
const caseStore = useCaseStore()

const props = defineProps<{
  hasCase?: boolean
  hasState?: boolean
  loading?: boolean
  disabled?: boolean
  stage?: string
}>()

const emit = defineEmits<{
  'extract': []
  'operate': []
  'simulate-recovery': []
}>()

const TOGGLES = [
  { key: 'showDamageZone' as const, label: 'Damage zone overlay' },
  { key: 'showBloodFlow' as const, label: 'Blood flow particles' },
  { key: 'showElectricalOverlay' as const, label: 'Electrical wave overlay' },
]

type StepStatus = 'idle' | 'ready' | 'complete' | 'running'

function stepStatus(required: boolean, complete: boolean, running: boolean): StepStatus {
  if (running) return 'running'
  if (complete) return 'complete'
  if (required) return 'ready'
  return 'idle'
}

const pipelineSteps = computed(() => {
  const hasFiles = caseStore.files.length > 0
  const hasVitals = Object.keys(caseStore.validatedFields).length > 0 || hasFiles
  const hasExtracted = caseStore.hasExtracted
  const hasOperated = !!caseStore.state
  const hasRecovery = caseStore.hasRecovery
  const isLoading = props.loading ?? false

  const steps = [
    {
      n: 1,
      label: 'Input',
      status: stepStatus(true, hasFiles || hasVitals, false) as StepStatus,
    },
    {
      n: 2,
      label: 'Extract',
      status: stepStatus(props.hasCase ?? false, hasExtracted, isLoading && (props.stage?.includes('1-3') ?? false)) as StepStatus,
    },
    {
      n: 3,
      label: 'Operate',
      status: stepStatus(hasExtracted, hasOperated, isLoading && (props.stage?.includes('4-5') ?? false)) as StepStatus,
    },
    {
      n: 4,
      label: 'Simulate Recovery',
      status: stepStatus(hasOperated, hasRecovery, isLoading && (props.stage?.includes('6-7') ?? false)) as StepStatus,
    },
    {
      n: 5,
      label: 'Inspect Trace',
      status: stepStatus(hasExtracted, caseStore.stageResults.length > 0, false) as StepStatus,
    },
  ]

  return steps.map(s => ({
    ...s,
    badge: s.status === 'running' ? 'Running' : s.status === 'complete' ? 'Complete' : s.status === 'ready' ? 'Ready' : '—',
    statusClass: {
      'bg-green-900/60 text-green-400 border border-green-700': s.status === 'complete',
      'bg-cardiac-red/20 text-white border border-cardiac-red/40': s.status === 'ready',
      'bg-blue-900/60 text-blue-400 border border-blue-700 animate-pulse': s.status === 'running',
      'bg-cardiac-navy-card text-cardiac-muted border border-cardiac-navy-border': s.status === 'idle',
    },
    labelClass: {
      'text-white': s.status === 'ready' || s.status === 'running',
      'text-green-400': s.status === 'complete',
      'text-cardiac-muted': s.status === 'idle',
    },
    badgeClass: {
      'bg-green-900/40 text-green-400': s.status === 'complete',
      'bg-cardiac-red/20 text-cardiac-red-glow': s.status === 'ready',
      'bg-blue-900/40 text-blue-400': s.status === 'running',
      'text-cardiac-muted': s.status === 'idle',
    },
  }))
})
</script>

<style scoped>
.section-title {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.btn-primary,
.btn-secondary {
  min-height: 2.4rem;
  border-radius: var(--ht-radius-sm);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-weight: 700;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.btn-primary {
  color: #fff;
  background: linear-gradient(135deg, var(--ht-red), #cf123f);
  border: 1px solid rgba(255, 255, 255, 0.10);
}

.btn-primary:not(:disabled):hover {
  box-shadow: var(--ht-shadow-glow-red);
  transform: translateY(-1px);
}

.btn-secondary {
  color: var(--ht-muted);
  background: rgba(10, 20, 35, 0.76);
  border: 1px solid var(--ht-border);
}

.btn-secondary:not(:disabled):hover {
  color: var(--ht-text);
  border-color: rgba(56, 189, 248, 0.35);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

@media (prefers-reduced-motion: reduce) {
  .btn-primary,
  .btn-secondary {
    transition: none;
  }

  .btn-primary:not(:disabled):hover {
    transform: none;
  }
}
</style>
