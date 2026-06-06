<template>
  <div
    :class="[
      'metric-card',
      statusModifier,
      compact && 'py-2 px-3',
    ]"
    :aria-label="`${title ?? label}: ${displayValue} ${unit ?? ''}`"
  >
    <!-- Header row -->
    <div class="flex items-start justify-between gap-1 min-w-0">
      <span class="metric-label leading-snug truncate">{{ title ?? label }}</span>
      <div class="flex items-center gap-1 shrink-0">
        <span v-if="trend === 'up'"   class="text-green-400 text-xs leading-none" aria-label="trending up">↑</span>
        <span v-else-if="trend === 'down'" class="text-cardiac-red text-xs leading-none" aria-label="trending down">↓</span>
        <UncertaintyBadge
          v-if="source && confidence != null && !isMissing"
          :source="source"
          :confidence="confidence"
        />
      </div>
    </div>

    <!-- Value row -->
    <div class="flex items-end gap-1 mt-0.5">
      <span
        :class="[
          compact ? 'metric-value-sm' : 'metric-value',
          isMissing && 'opacity-35',
          valueColorClass,
        ]"
      >
        {{ displayValue }}
      </span>
      <span v-if="unit && !isMissing" class="metric-unit pb-px">{{ unit }}</span>
    </div>

    <!-- Status line -->
    <div v-if="statusLineText || description" class="mt-0.5 flex items-center gap-1">
      <span v-if="statusLineText" :class="['text-[10px] font-mono', statusLineColor]">
        {{ statusLineText }}
      </span>
      <span v-else-if="description" class="text-[10px] font-mono truncate" style="color:rgba(148,163,184,0.55)">
        {{ description }}
      </span>
    </div>

    <!-- Confidence bar -->
    <div v-if="showBar && typeof numericValue === 'number' && !isMissing" class="mt-2">
      <div class="confidence-bar">
        <div
          class="confidence-fill"
          :class="barColorClass"
          :style="{ width: `${barPercent}%` }"
          role="progressbar"
          :aria-valuenow="barPercent"
          :aria-valuemin="0"
          :aria-valuemax="100"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ValueSource } from '~/types/heart'

const props = withDefaults(defineProps<{
  label?: string
  title?: string
  value: number | string | null | undefined
  unit?: string
  source?: ValueSource
  confidence?: number
  description?: string
  showBar?: boolean
  barMin?: number
  barMax?: number
  decimals?: number
  trend?: 'up' | 'down' | 'flat'
  isMissing?: boolean
  status?: 'normal' | 'warning' | 'critical' | 'good'
  compact?: boolean
}>(), {
  unit: '',
  confidence: undefined,
  description: '',
  showBar: false,
  barMin: 0,
  barMax: 100,
  decimals: 1,
  isMissing: false,
  status: 'normal',
  compact: false,
})

const numericValue = computed(() =>
  typeof props.value === 'number' ? props.value : null,
)

const displayValue = computed(() => {
  if (props.isMissing || props.value == null) return '—'
  if (typeof props.value === 'number') return props.value.toFixed(props.decimals)
  return String(props.value)
})

const barPercent = computed(() => {
  if (numericValue.value == null) return 0
  const range = props.barMax - props.barMin
  if (range === 0) return 0
  return Math.min(100, Math.max(0, ((numericValue.value - props.barMin) / range) * 100))
})

const barColorClass = computed(() => {
  const conf = props.confidence ?? 1
  if (conf >= 0.85) return 'bg-cardiac-safe'
  if (conf >= 0.65) return 'bg-cardiac-warn'
  if (conf >= 0.40) return 'bg-cardiac-pulse'
  return 'bg-cardiac-muted/50'
})

const statusModifier = computed(() => {
  if (props.isMissing) return 'metric-card--missing'
  if (props.status === 'critical') return 'metric-card--critical'
  if (props.status === 'warning') return 'metric-card--warning'
  if (props.status === 'good') return 'metric-card--good'
  return ''
})

const valueColorClass = computed(() => {
  if (props.isMissing) return ''
  if (props.status === 'critical') return 'text-red-400'
  if (props.status === 'warning') return 'text-amber-400'
  if (props.status === 'good') return 'text-green-400'
  return ''
})

const statusLineText = computed(() => {
  if (props.isMissing) return props.source ? 'Model prior' : 'Unavailable'
  if (props.source === 'default_model_prior') return 'Model prior'
  if (props.source === 'derived') return 'Derived'
  return ''
})

const statusLineColor = computed(() => {
  if (props.isMissing) return 'text-cardiac-muted/40'
  if (props.source === 'default_model_prior') return 'text-amber-400/65'
  if (props.source === 'derived') return 'text-purple-400/70'
  return 'text-cardiac-muted/50'
})
</script>

<style scoped>
.metric-card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  padding: 0.75rem 0.875rem;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(8, 13, 26, 0.78));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.26);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.metric-card:hover {
  border-color: rgba(226, 232, 240, 0.20);
}

.metric-card--warning {
  background:
    linear-gradient(135deg, rgba(245, 158, 11, 0.10), rgba(8, 13, 26, 0.78));
  border-color: rgba(245, 158, 11, 0.36);
}

.metric-card--critical {
  background:
    linear-gradient(135deg, rgba(239, 68, 68, 0.10), rgba(8, 13, 26, 0.78));
  border-color: rgba(239, 68, 68, 0.42);
}

.metric-card--good {
  border-color: rgba(34, 197, 94, 0.30);
}

.metric-card--missing {
  border-style: dashed;
  border-color: rgba(148, 163, 184, 0.16);
  opacity: 0.72;
}

.metric-label {
  color: rgba(142, 160, 184, 0.78);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value,
.metric-value-sm {
  color: var(--ht-text);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.metric-value {
  font-size: 1.45rem;
}

.metric-value-sm {
  font-size: 1.05rem;
}

.metric-unit {
  color: rgba(142, 160, 184, 0.68);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
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

@media (prefers-reduced-motion: reduce) {
  .metric-card,
  .confidence-fill {
    transition: none;
  }
}
</style>
