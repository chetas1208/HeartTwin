<template>
  <div ref="containerRef" class="chart-shell w-full h-full relative">
    <div v-if="!hasData" class="absolute inset-0 flex items-center justify-center">
      <div class="text-center">
        <svg class="w-8 h-8 text-cardiac-red/30 mx-auto mb-2" viewBox="0 0 100 40" fill="none">
          <polyline points="0,20 15,20 20,5 25,35 30,20 40,20 45,10 50,30 55,20 70,20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" class="animate-ecg-line"/>
        </svg>
        <p class="text-xs text-cardiac-muted">No ECG data available</p>
        <p class="text-xs text-cardiac-muted/60 mt-1">Upload an ECG file or CSV waveform</p>
      </div>
    </div>
    <div v-else ref="plotRef" class="w-full h-full" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{
  timeMs?: number[]
  pressure?: number[]
  heartRateBpm?: number | null
  rhythmLabel?: string | null
}>()

const containerRef = ref<HTMLElement>()
const plotRef = ref<HTMLElement>()
let Plotly: typeof import('plotly.js-dist-min') | null = null

const hasData = computed(() => props.timeMs && props.timeMs.length > 0)

async function initPlotly() {
  if (!Plotly) {
    Plotly = await import('plotly.js-dist-min')
  }
}

async function renderChart() {
  if (!plotRef.value || !hasData.value || !props.timeMs || !props.pressure) return
  await initPlotly()
  if (!Plotly) return

  const trace = {
    x: props.timeMs,
    y: props.pressure,
    type: 'scatter' as const,
    mode: 'lines' as const,
    line: { color: '#e31b1b', width: 1.5, shape: 'linear' as const },
    name: 'LV Pressure',
    hovertemplate: '%{x:.0f}ms / %{y:.1f} mmHg<extra></extra>',
  }

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { t: 8, r: 8, b: 32, l: 44 },
    xaxis: {
      title: { text: 'Time (ms)', font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(227,27,27,0.08)',
      zerolinecolor: 'rgba(227,27,27,0.15)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    yaxis: {
      title: { text: 'Pressure (mmHg)', font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(227,27,27,0.08)',
      zerolinecolor: 'rgba(227,27,27,0.15)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    showlegend: false,
    font: { family: 'JetBrains Mono' },
  }

  await Plotly!.newPlot(plotRef.value, [trace], layout, {
    responsive: true,
    displayModeBar: false,
    staticPlot: false,
  })
}

async function destroyChart() {
  if (plotRef.value && Plotly) {
    await Plotly!.purge(plotRef.value)
  }
}

onMounted(async () => {
  await renderChart()
})

watch(() => [props.timeMs, props.pressure], async () => {
  await destroyChart()
  await renderChart()
})

onUnmounted(() => {
  destroyChart()
})
</script>

<style scoped>
.chart-shell {
  min-height: 11rem;
  background:
    linear-gradient(180deg, rgba(3, 7, 17, 0.28), rgba(10, 20, 35, 0.18));
  border-radius: var(--ht-radius-sm);
}

.chart-shell :deep(.plot-container) {
  font-family: "JetBrains Mono", ui-monospace, monospace;
}
</style>
