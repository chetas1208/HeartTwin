<template>
  <div class="chart-shell w-full h-full relative">
    <div v-if="!hasData" class="absolute inset-0 flex items-center justify-center">
      <div class="text-center">
        <p class="text-xs text-cardiac-muted">No PV loop data</p>
        <p class="text-xs text-cardiac-muted/60 mt-1">Run simulation to generate PV loop</p>
      </div>
    </div>
    <div v-else ref="plotRef" class="w-full h-full" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { PVLoopData } from '~/types/heart'

const props = defineProps<{
  pvLoop?: PVLoopData | null
}>()

const plotRef = ref<HTMLElement>()
let Plotly: typeof import('plotly.js-dist-min') | null = null

const hasData = computed(() => props.pvLoop && props.pvLoop.volumes_ml.length > 0)

async function initPlotly() {
  if (!Plotly) {
    Plotly = await import('plotly.js-dist-min')
  }
}

async function renderChart() {
  if (!plotRef.value || !hasData.value || !props.pvLoop) return
  await initPlotly()
  if (!Plotly) return

  const { volumes_ml, pressures_mmhg, edp_mmhg, peak_pressure_mmhg } = props.pvLoop

  const loopTrace = {
    x: [...volumes_ml, volumes_ml[0]],
    y: [...pressures_mmhg, pressures_mmhg[0]],
    type: 'scatter' as const,
    mode: 'lines' as const,
    fill: 'toself' as const,
    fillcolor: 'rgba(227,27,27,0.06)',
    line: { color: '#e31b1b', width: 2 },
    name: 'PV Loop',
    hovertemplate: '%{x:.1f} mL / %{y:.1f} mmHg<extra></extra>',
  }

  const edvPoint = {
    x: [Math.max(...volumes_ml)],
    y: [edp_mmhg],
    type: 'scatter' as const,
    mode: 'markers+text' as const,
    marker: { color: '#1a6fff', size: 8 },
    text: ['EDV'],
    textposition: 'bottom right' as const,
    textfont: { color: '#94a3b8', size: 9 },
    name: 'EDV',
    showlegend: false,
  }

  const esvPoint = {
    x: [Math.min(...volumes_ml)],
    y: [peak_pressure_mmhg * 0.8],
    type: 'scatter' as const,
    mode: 'markers+text' as const,
    marker: { color: '#1a6fff', size: 8 },
    text: ['ESV'],
    textposition: 'top right' as const,
    textfont: { color: '#94a3b8', size: 9 },
    name: 'ESV',
    showlegend: false,
  }

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { t: 8, r: 8, b: 36, l: 48 },
    xaxis: {
      title: { text: 'LV Volume (mL)', font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(26,111,255,0.08)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    yaxis: {
      title: { text: 'LV Pressure (mmHg)', font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(26,111,255,0.08)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    showlegend: false,
    annotations: [
      {
        x: 0.5, y: 1.0, xref: 'paper', yref: 'paper',
        text: `Area: ${props.pvLoop.pv_loop_area_mmhg_ml.toFixed(0)} mmHg·mL`,
        showarrow: false,
        font: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
        xanchor: 'center',
      },
    ],
  }

  await Plotly!.newPlot(plotRef.value, [loopTrace, edvPoint, esvPoint], layout, {
    responsive: true,
    displayModeBar: false,
  })
}

async function destroyChart() {
  if (plotRef.value && Plotly) await Plotly!.purge(plotRef.value)
}

onMounted(renderChart)
watch(() => props.pvLoop, async () => { await destroyChart(); await renderChart() })
onUnmounted(destroyChart)
</script>

<style scoped>
.chart-shell {
  min-height: 11rem;
  background:
    radial-gradient(circle at 50% 30%, rgba(56, 189, 248, 0.06), transparent 12rem),
    rgba(3, 7, 17, 0.24);
  border-radius: var(--ht-radius-sm);
}

.chart-shell :deep(.plot-container) {
  font-family: "JetBrains Mono", ui-monospace, monospace;
}
</style>
