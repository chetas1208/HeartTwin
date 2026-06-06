<template>
  <span
    :title="`Source: ${sourceLabel(source)} | Confidence: ${(confidence * 100).toFixed(0)}%`"
    :class="[
      'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-mono cursor-help',
      badgeClass,
    ]"
  >
    <span class="opacity-70">{{ shortLabel }}</span>
    <span class="opacity-90">{{ (confidence * 100).toFixed(0) }}%</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ValueSource } from '~/types/heart'
import { sourceLabel, sourceBadgeClass } from '~/utils/units'

const props = defineProps<{
  source: ValueSource
  confidence: number
}>()

const badgeClass = computed(() => sourceBadgeClass(props.source))

const shortLabel = computed(() => {
  const map: Record<string, string> = {
    extracted: 'EXT',
    user_input: 'USR',
    default_model_prior: 'PRI',
    computed: 'COM',
  }
  return map[props.source] ?? props.source.slice(0, 3).toUpperCase()
})
</script>

<style scoped>
span {
  border: 1px solid transparent;
}

.badge-user,
.bg-green-500\/10 {
  color: #86efac;
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.26);
}

.badge-extracted,
.bg-blue-500\/10 {
  color: #7dd3fc;
  background: rgba(56, 189, 248, 0.13);
  border-color: rgba(56, 189, 248, 0.28);
}

.badge-default,
.bg-amber-500\/10 {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.13);
  border-color: rgba(245, 158, 11, 0.30);
}
</style>
