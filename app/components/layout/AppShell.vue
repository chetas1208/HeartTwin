<template>
  <div class="app-shell min-h-screen">
    <TopNav />
    <main class="app-main pt-14">
      <slot />
    </main>

    <!-- Toast notifications -->
    <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      <TransitionGroup name="toast">
        <div
          v-for="toast in ui.toasts"
          :key="toast.id"
          :class="[
            'toast pointer-events-auto px-4 py-3 text-sm font-mono max-w-xs',
            toast.type === 'success' && 'bg-green-950 border-green-700 text-green-300',
            toast.type === 'error' && 'bg-red-950 border-red-700 text-red-300',
            toast.type === 'warning' && 'bg-amber-950 border-amber-700 text-amber-300',
            toast.type === 'info' && 'bg-cardiac-navy-card border-cardiac-navy-border text-cardiac-muted',
          ]"
        >
          {{ toast.message }}
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useUiStore } from '~/stores/ui'

const ui = useUiStore()
</script>

<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
  overflow-x: clip;
  background:
    radial-gradient(circle at 18% 14%, rgba(255, 54, 95, 0.12), transparent 26rem),
    radial-gradient(circle at 82% 8%, rgba(56, 189, 248, 0.11), transparent 28rem),
    var(--ht-bg);
}

.app-shell::before {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 54, 95, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 54, 95, 0.035) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.8), transparent 75%);
  content: "";
}

.app-main {
  position: relative;
  z-index: 1;
}

.toast {
  border: 1px solid currentColor;
  border-radius: var(--ht-radius-sm);
  box-shadow: var(--ht-shadow-panel);
  backdrop-filter: blur(12px);
}

.toast-enter-active, .toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active {
    transition: none;
  }
}
</style>
