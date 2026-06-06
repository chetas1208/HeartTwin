<template>
  <div :class="['glass-card', hover && 'glass-card-hover', padding && 'p-4']" v-bind="$attrs">
    <slot />
  </div>
</template>

<script setup lang="ts">
defineOptions({ inheritAttrs: false })
defineProps<{
  hover?: boolean
  padding?: boolean
}>()
</script>

<style scoped>
.glass-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.86), rgba(7, 17, 31, 0.70)),
    rgba(10, 20, 35, 0.72);
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 14px 48px rgba(0, 0, 0, 0.22);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.glass-card-hover {
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.glass-card-hover:hover {
  border-color: rgba(255, 54, 95, 0.34);
  box-shadow: var(--ht-shadow-panel), var(--ht-shadow-glow-red);
  transform: translateY(-1px);
}

@media (prefers-reduced-motion: reduce) {
  .glass-card-hover {
    transition: none;
  }

  .glass-card-hover:hover {
    transform: none;
  }
}
</style>
