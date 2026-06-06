<template>
  <div class="empty-state px-6" :class="compact ? 'py-8' : 'py-16'">
    <!-- Icon -->
    <div
      :class="[
        'rounded-2xl flex items-center justify-center mb-4 shrink-0',
        compact ? 'w-12 h-12' : 'w-16 h-16',
        iconBg,
      ]"
      aria-hidden="true"
    >
      <slot name="icon">
        <svg
          :class="compact ? 'w-6 h-6' : 'w-8 h-8'"
          :style="{ color: iconColor }"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
        >
          <path stroke-linecap="round" stroke-linejoin="round" :d="iconPath" />
        </svg>
      </slot>
    </div>

    <!-- Text -->
    <div class="space-y-2 max-w-xs">
      <p
        :class="[
          'font-mono font-semibold text-white',
          compact ? 'text-sm' : 'text-base',
        ]"
      >
        {{ title }}
      </p>
      <p
        :class="[
          'text-cardiac-muted leading-relaxed',
          compact ? 'text-xs' : 'text-sm',
        ]"
      >
        {{ description }}
      </p>
      <p v-if="hint" class="text-xs text-cardiac-muted/60 font-mono mt-1 italic">
        {{ hint }}
      </p>
    </div>

    <!-- Action slot -->
    <div v-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  title: string
  description: string
  hint?: string
  icon?: 'heart' | 'upload' | 'chart' | 'search' | 'trace' | 'warning' | 'check'
  compact?: boolean
}>(), {
  icon: 'heart',
  compact: false,
})

const iconPath = computed(() => {
  const paths: Record<string, string> = {
    heart: 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z',
    upload: 'M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5',
    chart: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
    search: 'M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z',
    trace: 'M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z',
    warning: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
    check: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  }
  return paths[props.icon] ?? paths.heart
})

const iconBg = computed(() => {
  const bgs: Record<string, string> = {
    heart: 'bg-cardiac-red/10',
    upload: 'bg-cardiac-blue/10',
    chart: 'bg-green-500/10',
    search: 'bg-purple-500/10',
    trace: 'bg-cardiac-blue/10',
    warning: 'bg-amber-500/10',
    check: 'bg-green-500/10',
  }
  return bgs[props.icon] ?? bgs.heart
})

const iconColor = computed(() => {
  const colors: Record<string, string> = {
    heart: '#e31b1b',
    upload: '#1a6fff',
    chart: '#22c55e',
    search: '#a855f7',
    trace: '#00d4ff',
    warning: '#f59e0b',
    check: '#22c55e',
  }
  return colors[props.icon] ?? colors.heart
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  text-align: center;
  background:
    radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.08), transparent 15rem),
    rgba(10, 20, 35, 0.28);
  border: 1px dashed rgba(148, 163, 184, 0.14);
  border-radius: var(--ht-radius-lg);
}
</style>
