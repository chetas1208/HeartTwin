<template>
  <div class="chart-shell w-full h-full relative">
    <div v-if="!hasData" class="absolute inset-0 flex items-center justify-center">
      <div class="text-center">
        <p class="text-xs text-cardiac-muted">No recovery scenarios available</p>
        <p class="text-xs text-cardiac-muted/60 mt-1">Run recovery simulation to see trajectories</p>
      </div>
    </div>
    <div v-else ref="plotRef" class="w-full h-full" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { RecoveryScenario } from '~/types/heart'

const props = defineProps<{
  scenarios?: RecoveryScenario[]
  metric?: 'ef_pct' | 'cardiac_output_l_min'
}>()

const plotRef = ref<HTMLElement>()
let Plotly: typeof import('plotly.js-dist-min') | null = null

const hasData = computed(() => props.scenarios && props.scenarios.length > 0)
const metric = computed(() => props.metric || 'ef_pct')

const SCENARIO_COLORS = ['#e31b1b', '#1a6fff', '#22c55e', '#f59e0b']

const metricLabel = computed(() => {
  return metric.value === 'ef_pct' ? 'Ejection Fraction (%)' : 'Cardiac Output (L/min)'
})

async function initPlotly() {
  if (!Plotly) {
    Plotly = await import('plotly.js-dist-min')
  }
}

async function renderChart() {
  if (!plotRef.value || !hasData.value || !props.scenarios) return
  await initPlotly()
  if (!Plotly) return

  const traces: unknown[] = []

  props.scenarios.forEach((scenario, i) => {
    const color = SCENARIO_COLORS[i % SCENARIO_COLORS.length]
    const days = scenario.trajectory.map((d) => d.day)
    const values = scenario.trajectory.map((d) => d[metric.value] as number)

    // Uncertainty is stored as CO-space values; derive a proportional fraction and
    // apply it to whatever metric is being displayed so bands are always readable.
    const low = scenario.trajectory.map((d) => {
      const co = d.cardiac_output_l_min
      const frac = co > 0 ? Math.max(0, (d.uncertainty_high - d.uncertainty_low) / (2 * co)) : 0.05
      const v = d[metric.value] as number
      return v * (1 - frac)
    })
    const high = scenario.trajectory.map((d) => {
      const co = d.cardiac_output_l_min
      const frac = co > 0 ? Math.max(0, (d.uncertainty_high - d.uncertainty_low) / (2 * co)) : 0.05
      const v = d[metric.value] as number
      return v * (1 + frac)
    })

    traces.push({
      x: [...days, ...days.slice().reverse()],
      y: [...high, ...low.slice().reverse()],
      type: 'scatter',
      fill: 'toself',
      fillcolor: `${color}18`,
      line: { color: 'transparent' },
      showlegend: false,
      hoverinfo: 'skip',
    })

    traces.push({
      x: days,
      y: values,
      type: 'scatter',
      mode: 'lines',
      line: { color, width: 2 },
      name: scenario.scenario_label,
      hovertemplate: `Day %{x}: %{y:.2f}<br><span style="color:${color}">${scenario.scenario_label}</span><extra></extra>`,
    })
  })

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { t: 8, r: 8, b: 36, l: 52 },
    xaxis: {
      title: { text: 'Day', font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(148,163,184,0.08)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    yaxis: {
      title: { text: metricLabel.value, font: { color: '#94a3b8', size: 10 } },
      color: '#94a3b8',
      gridcolor: 'rgba(148,163,184,0.08)',
      tickfont: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
    },
    legend: {
      font: { color: '#94a3b8', size: 9, family: 'JetBrains Mono' },
      bgcolor: 'rgba(0,0,0,0)',
    },
    showlegend: true,
  }

  await Plotly!.newPlot(plotRef.value, traces, layout, {
    responsive: true,
    displayModeBar: false,
  })
}

async function destroyChart() {
  if (plotRef.value && Plotly) await Plotly!.purge(plotRef.value)
}

onMounted(renderChart)
watch(() => [props.scenarios, props.metric], async () => { await destroyChart(); await renderChart() }, { deep: true })
onUnmounted(destroyChart)
</script>

<style scoped>
.chart-shell {
  min-height: 12rem;
  background:
    radial-gradient(circle at 20% 20%, rgba(255, 54, 95, 0.06), transparent 12rem),
    radial-gradient(circle at 80% 10%, rgba(56, 189, 248, 0.06), transparent 12rem),
    rgba(3, 7, 17, 0.24);
  border-radius: var(--ht-radius-sm);
}

.chart-shell :deep(.plot-container) {
  font-family: "JetBrains Mono", ui-monospace, monospace;
}
</style>
