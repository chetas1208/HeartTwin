<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-mono font-medium',
      classes[variant],
    ]"
    role="status"
    :aria-label="`Status: ${label}`"
  >
    <span
      v-if="dot"
      :class="['w-1.5 h-1.5 rounded-full shrink-0', dotClass[variant], pulse && 'animate-pulse']"
      aria-hidden="true"
    />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'sim'
  dot?: boolean
  pulse?: boolean
}>(), {
  variant: 'neutral',
  dot: false,
  pulse: false,
})

const classes: Record<string, string> = {
  success: 'bg-green-900/40 text-green-400 border border-green-700/50',
  warning: 'bg-amber-900/30 text-amber-400 border border-amber-700/40',
  error:   'bg-red-900/30 text-red-400 border border-red-700/40',
  info:    'bg-cardiac-blue/15 text-cardiac-electric border border-cardiac-blue/30',
  neutral: 'bg-cardiac-navy-card text-cardiac-muted border border-cardiac-navy-border',
  sim:     'bg-cardiac-blue/10 text-cardiac-electric border border-cardiac-blue/20',
}

const dotClass: Record<string, string> = {
  success: 'bg-green-400',
  warning: 'bg-amber-400',
  error:   'bg-red-400',
  info:    'bg-cardiac-electric',
  neutral: 'bg-cardiac-muted',
  sim:     'bg-cardiac-electric',
}
</script>

<style scoped>
span[role="status"] {
  border-radius: 999px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
</style>
