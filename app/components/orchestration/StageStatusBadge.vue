<template>
  <span :class="badgeClass" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-mono font-medium">
    <span :class="dotClass" class="w-1.5 h-1.5 rounded-full" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentStatus } from '~/types/api'

type StageStatus = AgentStatus | 'pending' | 'running'

const props = defineProps<{
  status: StageStatus
  label?: string
}>()

const badgeClass = computed(() => ({
  'bg-cardiac-safe/15 text-green-400 border border-cardiac-safe/30': props.status === 'success',
  'bg-cardiac-warn/15 text-amber-400 border border-cardiac-warn/30': props.status === 'warning',
  'bg-cardiac-red/15 text-red-400 border border-cardiac-red/30': props.status === 'failed',
  'bg-cardiac-blue/15 text-cardiac-electric border border-cardiac-blue/30': props.status === 'running',
  'bg-cardiac-muted/10 text-cardiac-muted border border-cardiac-navy-border': props.status === 'pending',
}))

const dotClass = computed(() => ({
  'bg-green-400': props.status === 'success',
  'bg-amber-400 animate-pulse': props.status === 'warning',
  'bg-red-400': props.status === 'failed',
  'bg-cardiac-electric animate-pulse': props.status === 'running',
  'bg-cardiac-muted': props.status === 'pending',
}))

const label = computed(() => {
  if (props.label) return props.label
  const map: Record<StageStatus, string> = {
    success: 'Success',
    warning: 'Warning',
    failed: 'Failed',
    running: 'Running',
    pending: 'Pending',
  }
  return map[props.status] ?? props.status
})
</script>

<style scoped>
span {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
</style>
