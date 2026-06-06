<template>
  <aside
    :class="[
      'side-panel h-full flex flex-col transition-all duration-200',
      open ? 'w-72' : 'w-0 overflow-hidden',
    ]"
  >
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <slot />
    </div>
  </aside>
</template>

<script setup lang="ts">
defineProps<{ open: boolean }>()
</script>

<style scoped>
.side-panel {
  background:
    linear-gradient(180deg, rgba(14, 28, 48, 0.94), rgba(3, 7, 17, 0.92));
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 16px 0 44px rgba(0, 0, 0, 0.24);
}

@media (prefers-reduced-motion: reduce) {
  .side-panel {
    transition: none;
  }
}
</style>
