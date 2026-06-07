<template>
  <div class="glass-card p-4 space-y-3">
    <div class="flex items-center justify-between">
      <h3 class="text-xs font-mono font-semibold text-white uppercase tracking-widest">System Check</h3>
      <button
        class="text-xs font-mono px-3 py-1.5 rounded border transition-colors"
        :class="running
          ? 'border-cardiac-navy-border text-cardiac-muted cursor-not-allowed'
          : 'border-cardiac-blue/40 text-cardiac-electric hover:bg-cardiac-blue/10'"
        :disabled="running"
        @click="runCheck"
      >
        <span v-if="running" class="flex items-center gap-1.5">
          <svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          Running…
        </span>
        <span v-else>Run Check</span>
      </button>
    </div>

    <!-- Pre-run state -->
    <p v-if="!result && !error && !running" class="text-xs text-cardiac-muted font-mono">
      Validates formulas, pipeline, and safety layer with golden-case inputs.
    </p>

    <!-- Error -->
    <p v-if="error" class="text-xs text-cardiac-red-glow font-mono">{{ error }}</p>

    <!-- Results -->
    <div v-if="result" class="space-y-1.5">
      <!-- Overall badge -->
      <div class="flex items-center gap-2 mb-2">
        <span
          class="text-xs font-mono px-2 py-0.5 rounded-full font-semibold"
          :class="result.status === 'ok' ? 'bg-green-900/50 text-green-400 border border-green-700' : 'bg-amber-900/50 text-amber-400 border border-amber-700'"
        >
          {{ result.status === 'ok' ? '✓ All systems nominal' : '⚠ Degraded' }}
        </span>
        <span class="text-xs text-cardiac-muted font-mono">{{ checkedAt }}</span>
      </div>

      <!-- Individual checks -->
      <div v-for="check in result.checks" :key="check.name" class="flex items-center justify-between py-1 border-b border-cardiac-navy-border/50 last:border-0">
        <span class="text-xs font-mono text-cardiac-muted capitalize">{{ check.name.replace(/_/g, ' ') }}</span>
        <div class="flex items-center gap-2">
          <span class="text-[10px] font-mono text-cardiac-muted/70 truncate max-w-[180px]" :title="check.message">{{ check.message }}</span>
          <span
            class="text-xs font-mono px-1.5 py-0.5 rounded"
            :class="check.status === 'ok'
              ? 'bg-green-900/40 text-green-400'
              : check.status === 'warning'
                ? 'bg-amber-900/40 text-amber-400'
                : 'bg-red-900/40 text-red-400'"
          >
            {{ check.status === 'ok' ? 'OK' : check.status === 'warning' ? 'WARN' : 'FAIL' }}
          </span>
        </div>
      </div>

      <!-- Metrics -->
      <div v-if="result.metrics && Object.keys(result.metrics).length" class="pt-2 mt-1 border-t border-cardiac-navy-border/50">
        <p class="text-[10px] font-mono uppercase tracking-widest text-cardiac-muted/60 mb-1">Golden metrics</p>
        <div class="flex flex-wrap gap-x-3 gap-y-1">
          <span v-for="(val, key) in result.metrics" :key="key" class="text-[10px] font-mono text-cardiac-muted">{{ key }}: {{ val }}</span>
        </div>
      </div>

      <!-- Integrations -->
      <div v-if="result.integrations" class="pt-2 mt-1 border-t border-cardiac-navy-border/50">
        <p class="text-[10px] font-mono uppercase tracking-widest text-cardiac-muted/60 mb-1">Integrations</p>
        <div class="flex flex-wrap gap-x-3 gap-y-1">
          <span v-for="(val, key) in result.integrations" :key="key" class="text-[10px] font-mono text-cardiac-muted">{{ key }}: {{ val }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const running = ref(false)
const error = ref<string | null>(null)
const checkedAt = ref('')

interface CheckResult {
  name: string
  status: string
  message: string
}
interface SystemCheckResponse {
  status: string
  checks: CheckResult[]
  metrics?: Record<string, number>
  integrations?: Record<string, string>
  warnings?: string[]
  failed_checks: string[]
}

const result = ref<SystemCheckResponse | null>(null)

async function runCheck() {
  running.value = true
  error.value = null
  result.value = null
  try {
    const config = useRuntimeConfig()
    const base = config.public.apiBase as string
    const resp = await fetch(`${base}/system-check`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    result.value = await resp.json()
    checkedAt.value = new Date().toLocaleTimeString()
  } catch (e) {
    error.value = `Check failed: ${String(e)}`
  } finally {
    running.value = false
  }
}
</script>

<style scoped>
.glass-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: var(--ht-radius-md);
  background:
    linear-gradient(145deg, rgba(10, 20, 35, 0.92), rgba(4, 10, 20, 0.72)),
    rgba(10, 20, 35, 0.72);
  box-shadow: var(--ht-shadow-panel);
  backdrop-filter: blur(18px);
}
</style>
