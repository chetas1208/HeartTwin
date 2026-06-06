<template>
  <div :class="['flex items-center justify-between gap-3', tight ? '' : 'mb-3']">
    <div class="flex items-center gap-2 min-w-0">
      <span
        v-if="dot"
        :class="['w-1.5 h-1.5 rounded-full shrink-0', dotColor]"
        aria-hidden="true"
      />
      <p class="section-title m-0">{{ title }}</p>
      <slot name="badge" />
    </div>
    <div class="shrink-0 flex items-center gap-1">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  dot?: boolean
  dotColor?: string
  tight?: boolean
}>(), {
  dot: false,
  dotColor: 'bg-cardiac-red',
  tight: false,
})
</script>

<style scoped>
.section-title {
  color: rgba(142, 160, 184, 0.72);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.section-title::after {
  display: block;
  width: 2.2rem;
  height: 1px;
  margin-top: 0.28rem;
  background: linear-gradient(90deg, var(--ht-red), transparent);
  content: "";
}
</style>
