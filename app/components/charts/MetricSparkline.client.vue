<template>
  <div class="metric-card group">
    <p class="metric-label">{{ label }}</p>
    <div class="flex items-end gap-2">
      <span class="metric-value">
        {{ value !== null ? value.toFixed(decimals) : '—' }}
      </span>
      <span class="metric-unit pb-1">{{ unit }}</span>
    </div>
    <div v-if="source" class="mt-1">
      <UncertaintyBadge :source="source" :confidence="confidence ?? 0.5" />
    </div>
    <div v-if="trend !== null && trend !== undefined" class="mt-1 flex items-center gap-1 text-xs">
      <svg v-if="trend > 0" class="w-3 h-3 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7 7 7"/>
      </svg>
      <svg v-else-if="trend < 0" class="w-3 h-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7-7-7"/>
      </svg>
      <span :class="trend > 0 ? 'text-green-400' : trend < 0 ? 'text-red-400' : 'text-cardiac-muted'">
        {{ trend > 0 ? '+' : '' }}{{ trend.toFixed(1) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ValueSource } from '~/types/heart'

defineProps<{
  label: string
  value: number | null
  unit?: string
  decimals?: number
  source?: ValueSource
  confidence?: number
  trend?: number | null
}>()
</script>

<style scoped>
.metric-card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem 0.875rem;
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.88), rgba(7, 17, 31, 0.72));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.24);
}

.metric-label {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-value {
  color: var(--ht-text);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.metric-unit {
  color: rgba(142, 160, 184, 0.68);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
}
</style>
