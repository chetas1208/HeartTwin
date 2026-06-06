<template>
  <div class="space-y-1">
    <label class="metric-label">{{ label }} <span v-if="unit" class="text-cardiac-muted normal-case font-normal">{{ unit }}</span></label>
    <input
      type="number"
      :value="modelValue ?? ''"
      :min="min"
      :max="max"
      :placeholder="placeholder"
      class="w-full bg-cardiac-navy border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-cardiac-muted focus:outline-none focus:border-cardiac-red/50"
      :class="error ? 'border-red-500' : 'border-cardiac-navy-border'"
      @input="onInput"
    >
    <p v-if="error" class="text-xs text-red-400 font-mono">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  modelValue?: number
  label: string
  unit?: string
  min?: number
  max?: number
  placeholder?: string
  error?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number | undefined]
}>()

function onInput(e: Event) {
  const raw = (e.target as HTMLInputElement).value
  emit('update:modelValue', raw === '' ? undefined : Number(raw))
}
</script>

<style scoped>
.metric-label {
  color: rgba(142, 160, 184, 0.78);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

input {
  background: rgba(3, 7, 17, 0.82);
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

input:focus {
  border-color: rgba(56, 189, 248, 0.55);
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
}

input.border-red-500 {
  border-color: rgba(239, 68, 68, 0.75);
}
</style>
