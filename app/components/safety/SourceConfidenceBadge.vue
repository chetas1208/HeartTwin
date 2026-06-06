<template>
  <span :class="badgeClass" class="inline-flex items-center gap-1 text-xs font-mono">
    <span class="opacity-60">{{ sourceText }}</span>
    <span class="font-semibold">{{ confidenceText }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ValueSource } from '~/types/heart'
import { sourceLabel } from '~/utils/units'

const props = defineProps<{
  source: ValueSource
  confidence: number
  method?: string | null
}>()

const sourceText = computed(() => sourceLabel(props.source))

const confidenceText = computed(() => {
  const pct = Math.round(props.confidence * 100)
  return `${pct}%`
})

const badgeClass = computed(() => {
  const src = props.source
  if (src === 'user_input') return 'badge-user'
  if (src === 'file_extraction') return 'badge-extracted'
  if (src === 'derived') return 'badge-extracted'
  return 'badge-default'
})
</script>

<style scoped>
span {
  padding: 0.125rem 0.4rem;
  border-radius: 0.375rem;
  border: 1px solid transparent;
}

.badge-user {
  color: #86efac;
  background: rgba(34, 197, 94, 0.12);
  border-color: rgba(34, 197, 94, 0.26);
}

.badge-extracted {
  color: #7dd3fc;
  background: rgba(56, 189, 248, 0.13);
  border-color: rgba(56, 189, 248, 0.28);
}

.badge-default {
  color: #fbbf24;
  background: rgba(245, 158, 11, 0.13);
  border-color: rgba(245, 158, 11, 0.30);
}
</style>
