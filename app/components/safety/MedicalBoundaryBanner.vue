<template>
  <Transition name="banner-slide">
    <div
      v-if="!dismissed"
      class="medical-boundary-bar"
      role="alert"
      aria-label="Medical safety boundary notice"
    >
      <!-- Shield icon -->
      <svg class="w-3 h-3 shrink-0 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
      </svg>

      <span class="flex-1">
        <span class="font-semibold" style="color:rgba(251,191,36,0.85)">Educational simulation only.</span>
        <span class="ml-1 hidden sm:inline opacity-75">
          Not for diagnosis or treatment decisions.
        </span>
        <span class="ml-1 sm:hidden opacity-75">Not for diagnosis or treatment decisions.</span>
      </span>

      <button
        v-if="dismissible"
        class="shrink-0 ml-2 opacity-50 hover:opacity-90 transition-opacity rounded"
        style="padding: 2px;"
        aria-label="Dismiss safety notice"
        @click="dismissed = true"
      >
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref } from 'vue'

withDefaults(defineProps<{
  dismissible?: boolean
}>(), {
  dismissible: false,
})

const dismissed = ref(false)
</script>

<style scoped>
.medical-boundary-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.875rem;
  color: rgba(251, 191, 36, 0.78);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.66rem;
  line-height: 1.45;
  background:
    linear-gradient(90deg, rgba(245, 158, 11, 0.10), rgba(56, 189, 248, 0.05));
  border: 1px solid rgba(245, 158, 11, 0.20);
  border-radius: var(--ht-radius-sm);
}

.medical-boundary-bar button:focus-visible {
  outline-color: var(--ht-amber);
}

.banner-slide-enter-active,
.banner-slide-leave-active {
  transition: all 0.25s ease;
}
.banner-slide-enter-from,
.banner-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
  max-height: 0;
}

@media (prefers-reduced-motion: reduce) {
  .banner-slide-enter-active,
  .banner-slide-leave-active {
    transition: none;
  }
}
</style>
