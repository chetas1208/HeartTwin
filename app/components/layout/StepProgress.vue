<template>
  <div class="flex items-center gap-0 w-full" role="list" :aria-label="label ?? 'Progress steps'">
    <div
      v-for="(step, i) in steps"
      :key="step.key"
      class="flex items-center"
      :class="i < steps.length - 1 ? 'flex-1' : ''"
      role="listitem"
    >
      <!-- Step node -->
      <button
        type="button"
        :class="[
          'flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono transition-colors duration-150',
          step.status === 'done'    && 'text-green-400',
          step.status === 'active'  && 'text-white',
          step.status === 'ready'   && 'text-cardiac-muted hover:text-white',
          step.status === 'idle'    && 'text-cardiac-muted/50 cursor-default',
        ]"
        :aria-current="step.status === 'active' ? 'step' : undefined"
        :disabled="step.status === 'idle'"
        @click="step.status !== 'idle' && emit('step-click', step.key)"
      >
        <!-- Icon -->
        <span
          :class="[
            'w-4 h-4 rounded-full text-[10px] flex items-center justify-center shrink-0 font-bold',
            step.status === 'done'    && 'bg-green-900/60 border border-green-700 text-green-400',
            step.status === 'active'  && 'bg-cardiac-red text-white',
            step.status === 'ready'   && 'bg-cardiac-navy-card border border-cardiac-navy-border text-cardiac-muted',
            step.status === 'idle'    && 'bg-cardiac-navy border border-cardiac-navy-border/40 text-cardiac-muted/30',
          ]"
          aria-hidden="true"
        >
          <svg v-if="step.status === 'done'" class="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 12 12">
            <path d="M10 3L5 8.5 2 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
          </svg>
          <svg v-else-if="step.status === 'active'" class="w-2 h-2 animate-pulse" fill="currentColor" viewBox="0 0 8 8">
            <circle cx="4" cy="4" r="3"/>
          </svg>
          <span v-else>{{ i + 1 }}</span>
        </span>
        <span class="hidden sm:inline">{{ step.label }}</span>
      </button>

      <!-- Connector line -->
      <div
        v-if="i < steps.length - 1"
        :class="[
          'flex-1 h-px mx-1',
          step.status === 'done' ? 'bg-green-700/50' : 'bg-cardiac-navy-border/60',
        ]"
        aria-hidden="true"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
export type StepStatus = 'idle' | 'ready' | 'active' | 'done'

export interface Step {
  key: string
  label: string
  status: StepStatus
}

defineProps<{
  steps: Step[]
  label?: string
}>()

const emit = defineEmits<{
  'step-click': [key: string]
}>()
</script>

<style scoped>
button {
  min-height: 1.75rem;
}

button:not(:disabled):hover {
  background: rgba(56, 189, 248, 0.08);
}

button[aria-current="step"] {
  background: rgba(255, 54, 95, 0.12);
  box-shadow: 0 0 20px rgba(255, 54, 95, 0.14);
}

@media (prefers-reduced-motion: reduce) {
  button {
    transition: none;
  }
}
</style>
