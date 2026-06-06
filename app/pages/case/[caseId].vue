<template>
  <AppShell :show-nav="true">
    <div class="max-w-6xl mx-auto px-4 py-6 space-y-4">

      <!-- ══════════════════════════════════
           Case Header
      ══════════════════════════════════ -->
      <div class="flex items-center gap-3">
        <NuxtLink
          to="/lab"
          class="w-8 h-8 flex items-center justify-center rounded-lg transition-colors shrink-0"
          style="color:rgba(148,163,184,0.6); background:rgba(16,42,80,0.3);"
          aria-label="Back to Lab"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
        </NuxtLink>
        <div class="flex-1 min-w-0">
          <h1 class="text-base font-mono font-semibold text-white truncate" aria-live="polite">
            Case <span class="text-cardiac-electric">{{ caseId?.slice(0, 10) }}</span>
            <span style="color:rgba(148,163,184,0.4)">…</span>
          </h1>
          <div class="flex items-center gap-2 mt-0.5">
            <div
              v-if="caseData?.status"
              class="w-1.5 h-1.5 rounded-full"
              :style="{background: statusDotColor}"
              aria-hidden="true"
            />
            <p class="text-xs font-mono" style="color:rgba(148,163,184,0.55)">
              {{ caseData?.status || (loading ? 'Loading…' : 'Unknown') }}
            </p>
          </div>
        </div>

        <!-- DQ badge -->
        <div v-if="dqs > 0" class="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono shrink-0"
          :class="dqs >= 0.75 ? 'text-green-400' : dqs >= 0.5 ? 'text-amber-400' : 'text-red-400'"
          style="background:rgba(16,42,80,0.5); border:1px solid rgba(16,42,80,0.8);"
        >
          <span style="color:rgba(148,163,184,0.45)">DQ</span>
          <span class="font-semibold tabular-nums">{{ Math.round(dqs * 100) }}%</span>
        </div>
        <span class="sim-label shrink-0">SIMULATION ONLY</span>
      </div>

      <MedicalBoundaryBanner />

      <!-- ══════════════════════════════════
           Tab navigation
      ══════════════════════════════════ -->
      <nav class="tab-bar" aria-label="Case workspace tabs">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          :class="activeTab === tab.key ? 'tab-item-active' : 'tab-item-inactive'"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>

      <!-- Loading state -->
      <div v-if="loading" class="flex items-center justify-center py-20" aria-live="polite" aria-busy="true">
        <svg class="w-6 h-6 animate-spin mr-3" style="color:#e31b1b;" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span class="text-sm font-mono" style="color:rgba(148,163,184,0.65)">Loading case…</span>
      </div>

      <!-- Error state -->
      <div v-else-if="error" class="inline-error" role="alert">
        <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
        </svg>
        Failed to load case: {{ error }}
      </div>

      <!-- ══════════════════════════════════
           TAB: Overview
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'overview'">
        <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4 animate-fade-in">

          <!-- Data Quality -->
          <GlassCard class="p-4 col-span-full lg:col-span-1">
            <p class="panel-label mb-3">Data Quality</p>
            <div class="flex items-center gap-3">
              <div class="flex-1 progress-track h-2">
                <div
                  class="progress-fill h-2"
                  :class="dqs >= 0.75 ? 'bg-cardiac-safe' : dqs >= 0.5 ? 'bg-cardiac-warn' : 'bg-cardiac-red'"
                  :style="{ width: `${Math.round(dqs * 100)}%` }"
                />
              </div>
              <span class="text-sm font-mono font-semibold text-white tabular-nums w-10 text-right">
                {{ Math.round(dqs * 100) }}%
              </span>
            </div>
            <p class="text-[10px] font-mono mt-2" style="color:rgba(148,163,184,0.4)">
              {{ dqs >= 0.75 ? 'Good — sufficient data for simulation' : dqs >= 0.5 ? 'Moderate — some values rely on model priors' : 'Low — results may be unreliable' }}
            </p>
          </GlassCard>

          <MetricCard
            v-for="m in overviewMetrics"
            :key="m.label"
            :label="m.label"
            :value="m.value"
            :unit="m.unit"
            :source="m.source"
            :confidence="m.confidence"
            :show-bar="m.showBar"
            :bar-min="m.barMin"
            :bar-max="m.barMax"
            :decimals="m.decimals ?? 1"
          />

          <!-- Next action -->
          <GlassCard class="p-4 col-span-full flex items-start gap-3">
            <div class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" style="background:rgba(26,111,255,0.12); border:1px solid rgba(26,111,255,0.25);">
              <svg class="w-3.5 h-3.5" style="color:#7bb8ff" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/>
              </svg>
            </div>
            <div>
              <p class="text-xs font-mono font-semibold" style="color:#7bb8ff">Next product action</p>
              <p class="text-xs font-mono mt-0.5" style="color:rgba(148,163,184,0.7)">{{ nextAction }}</p>
            </div>
          </GlassCard>

          <!-- Warnings -->
          <GlassCard v-if="warnings.length" class="p-4 col-span-full">
            <p class="panel-label mb-3">Warnings</p>
            <ul class="space-y-1.5">
              <li v-for="w in warnings" :key="w" class="inline-warn">
                <svg class="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
                </svg>
                {{ w }}
              </li>
            </ul>
          </GlassCard>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Files
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'files'">
        <div class="space-y-2 animate-fade-in">
          <EmptyState
            v-if="!files.length"
            title="No files uploaded"
            description="Upload PDF reports, ECG images, or CSV waveforms in the Lab to extract evidence."
            icon="upload"
          />
          <GlassCard v-for="f in files" :key="f.file_id" class="p-4 flex items-center gap-4">
            <div class="text-xl shrink-0" aria-hidden="true">{{ fileIcon(f.content_type) }}</div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-mono text-white truncate">{{ f.filename }}</p>
              <p class="text-xs font-mono mt-0.5" style="color:rgba(148,163,184,0.5)">
                {{ f.content_type }} · {{ formatBytes(f.size_bytes) }}
              </p>
            </div>
            <span class="badge-extracted">{{ f.file_id.slice(0, 8) }}</span>
          </GlassCard>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Extracted Evidence
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'extracted'">
        <div class="space-y-2 animate-fade-in">
          <EmptyState
            v-if="!validatedFields || !Object.keys(validatedFields).length"
            title="No extracted evidence"
            description="Upload files and run extraction to populate evidence. Each field will show its source, confidence, and evidence snippet."
            icon="search"
          />
          <GlassCard v-for="(entry, field) in validatedFields" :key="String(field)" class="p-4">
            <div class="flex items-start justify-between gap-3">
              <div class="flex-1 min-w-0">
                <p class="text-[10px] font-mono uppercase tracking-widest mb-1" style="color:rgba(148,163,184,0.5)">{{ field }}</p>
                <p class="text-lg font-mono text-white font-semibold tabular-nums">{{ formatEntry(entry) }}</p>
                <p
                  v-if="(entry as any)?.raw_evidence || (entry as any)?.evidence"
                  class="text-xs font-mono mt-1.5 italic leading-relaxed"
                  style="color:rgba(148,163,184,0.5)"
                >
                  "{{ (entry as any).evidence || (entry as any).raw_evidence }}"
                </p>
              </div>
              <SourceConfidenceBadge
                v-if="(entry as any)?.source && (entry as any)?.confidence != null"
                :source="(entry as any).source"
                :confidence="(entry as any).confidence"
                :method="(entry as any).method"
                class="shrink-0 mt-1"
              />
            </div>
          </GlassCard>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Cardiac State
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'state'">
        <div class="animate-fade-in">
          <EmptyState
            v-if="!state"
            title="No cardiac state"
            description="Run operation in the Lab to build the canonical cardiac state from extracted evidence."
            icon="heart"
          />
          <div v-else class="space-y-4">
            <StateSection title="Measurements" :fields="measurementFields" />
            <StateSection title="Electrophysiology" :fields="epFields" />
            <StateSection title="Hemodynamics" :fields="hdFields" />
            <StateSection title="Tissue State" :fields="tissueFields" />
          </div>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Operation
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'operation'">
        <div class="animate-fade-in">
          <EmptyState
            v-if="!simResult"
            title="No operation simulation"
            description="Run the operation simulation in the Lab to generate cardiac cycle data, PV loop, and hemodynamic metrics."
            icon="chart"
          />
          <template v-else>
            <div class="grid md:grid-cols-2 gap-4">
              <GlassCard class="p-4 h-56">
                <p class="panel-label mb-2">Cardiac Cycle · LV Pressure</p>
                <ClientOnly>
                  <EcgTrace
                    :time-ms="(simResult.cardiac_cycle as any)?.time_ms"
                    :pressure="(simResult.cardiac_cycle as any)?.lv_pressure_mmhg"
                    :heart-rate-bpm="(simResult.summary as any)?.heart_rate_bpm"
                  />
                </ClientOnly>
                <p class="text-[9px] font-mono mt-1" style="color:rgba(148,163,184,0.35)">Simulated visualization · not for diagnosis or treatment decisions</p>
              </GlassCard>
              <GlassCard class="p-4 h-56">
                <p class="panel-label mb-2">Pressure–Volume Loop</p>
                <ClientOnly>
                  <PressureVolumeLoop :pv-loop="(simResult.pv_loop as any)" />
                </ClientOnly>
                <p class="text-[9px] font-mono mt-1" style="color:rgba(148,163,184,0.35)">Deterministic hemodynamics model</p>
              </GlassCard>
            </div>
            <GlassCard class="p-4 mt-4">
              <p class="panel-label mb-3">Summary Metrics</p>
              <div class="grid grid-cols-2 sm:grid-cols-5 gap-3">
                <MetricCard
                  v-for="m in opSummaryMetrics"
                  :key="m.label"
                  :label="m.label"
                  :value="m.value"
                  :unit="m.unit"
                  :decimals="m.decimals ?? 1"
                />
              </div>
            </GlassCard>
          </template>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Recovery Scenarios
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'recovery'">
        <div class="animate-fade-in">
          <EmptyState
            v-if="!scenarios?.length"
            title="No recovery scenarios"
            description="Run recovery simulation in the Lab to generate bounded trajectory scenarios with uncertainty bands."
            icon="chart"
          />
          <template v-else>
            <div
              class="flex items-center gap-2 px-3 py-2 rounded-lg mb-4 text-xs font-mono"
              style="background:rgba(26,111,255,0.08); border:1px solid rgba(26,111,255,0.18); color:rgba(0,212,255,0.75);"
            >
              <svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/>
              </svg>
              Recovery scenarios are bounded model simulations and not for diagnosis or treatment decisions.
            </div>

            <GlassCard class="p-4 h-64 mb-4">
              <ClientOnly>
                <RecoveryTimeline :scenarios="(scenarios as any)" />
              </ClientOnly>
            </GlassCard>

            <div class="grid md:grid-cols-2 gap-4">
              <GlassCard v-for="sc in scenarios" :key="sc.scenario_type" class="p-4 space-y-3">
                <div class="flex items-start justify-between gap-2">
                  <p class="text-xs font-mono font-semibold text-white">{{ sc.scenario_label }}</p>
                  <span class="sim-label text-[10px]">simulated</span>
                </div>
                <div class="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div class="data-field"><span class="data-key">EF Δ</span><span :class="sc.summary_metrics.ef_delta_pct >= 0 ? 'text-green-400' : 'text-red-400'" class="font-semibold">{{ sc.summary_metrics.ef_delta_pct >= 0 ? '+' : '' }}{{ sc.summary_metrics.ef_delta_pct?.toFixed(1) }}%</span></div>
                  <div class="data-field"><span class="data-key">CO Δ</span><span :class="sc.summary_metrics.co_delta_l_min >= 0 ? 'text-green-400' : 'text-red-400'" class="font-semibold">{{ sc.summary_metrics.co_delta_l_min >= 0 ? '+' : '' }}{{ sc.summary_metrics.co_delta_l_min?.toFixed(3) }}</span></div>
                  <div class="data-field"><span class="data-key">Final EF</span><span class="data-value">{{ sc.summary_metrics.final_ef_pct?.toFixed(1) }}%</span></div>
                  <div class="data-field"><span class="data-key">Horizon</span><span class="data-value">{{ sc.summary_metrics.horizon_days }}d</span></div>
                </div>
                <ul v-if="sc.warnings?.length" class="space-y-0.5">
                  <li v-for="w in sc.warnings.slice(0, 2)" :key="w" class="inline-warn text-[10px] py-1">
                    <svg class="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
                    </svg>
                    {{ w }}
                  </li>
                </ul>
              </GlassCard>
            </div>
          </template>
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Agent Trace
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'trace'">
        <div class="animate-fade-in">
          <EmptyState
            v-if="!stageResults?.length"
            title="No agent trace"
            description="Run the pipeline in the Lab to generate an agent decision trace."
            icon="trace"
          />
          <AgentTraceTimeline v-else :responses="stageResults" />
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Harness
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'harness'">
        <div class="animate-fade-in">
          <HarnessPanel
            :responses="stageResults"
            :evaluation="latestEvaluation"
            :weave="weaveInfo"
            :traces="traceEvents"
            :has-recovery="scenarios.length > 0"
            :self-improvement="selfImprovement"
            :loading="selfImproveLoading"
            @improve="runSelfImprove"
          />
        </div>
      </template>

      <!-- ══════════════════════════════════
           TAB: Safety & Uncertainty
      ══════════════════════════════════ -->
      <template v-else-if="activeTab === 'safety'">
        <div class="space-y-4 animate-fade-in">
          <!-- Medical boundary -->
          <GlassCard class="p-5 space-y-3" style="border-color:rgba(245,158,11,0.18);">
            <div class="flex items-center gap-2 mb-1">
              <svg class="w-4 h-4" style="color:rgba(251,191,36,0.8)" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
              </svg>
              <h3 class="text-sm font-semibold text-white">Medical Safety Boundary</h3>
            </div>
            <p class="text-xs leading-relaxed" style="color:rgba(148,163,184,0.7)">
              {{ caseData?.safety_disclaimer || 'HeartTwin Lab is an educational cardiac simulation tool. All outputs are simulated estimates. This is not a medical device and is not for diagnosis or treatment decisions.' }}
            </p>
            <div class="grid sm:grid-cols-2 gap-2 mt-2">
              <div
                v-for="item in SAFETY_ITEMS"
                :key="item"
                class="flex items-center gap-2 text-xs font-mono"
                style="color:rgba(74,222,128,0.75);"
              >
                <svg class="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75"/>
                </svg>
                {{ item }}
              </div>
            </div>
          </GlassCard>

          <!-- Source map -->
          <GlassCard v-if="sourceMap?.length" class="p-4">
            <p class="panel-label mb-3">Source Confidence Map</p>
            <div class="space-y-0 max-h-96 overflow-y-auto">
              <div
                v-for="entry in sourceMap"
                :key="entry.field"
                class="data-field"
              >
                <span class="data-key truncate flex-1">{{ entry.field }}</span>
                <div class="flex items-center gap-2 shrink-0">
                  <SourceConfidenceBadge
                    :source="entry.source"
                    :confidence="entry.confidence"
                    :method="entry.method"
                  />
                  <span v-if="entry.value != null" class="data-value">
                    {{ entry.value }} {{ entry.unit }}
                  </span>
                </div>
              </div>
            </div>
          </GlassCard>

          <!-- Uncertainty explanation -->
          <GlassCard class="p-5 space-y-2">
            <p class="panel-label mb-2">Uncertainty Explanation</p>
            <p class="text-xs leading-relaxed" style="color:rgba(148,163,184,0.65)">
              All values carry a source label and confidence score. Values marked <strong class="text-amber-400">Model prior</strong> use
              physiologically typical defaults when no data is available. Values marked <strong class="text-purple-400">Derived</strong>
              are computed from other extracted values. Values marked <strong class="text-blue-400">Extracted</strong>
              come from your uploaded files via the 8-agent pipeline.
            </p>
            <p class="text-xs leading-relaxed mt-1" style="color:rgba(148,163,184,0.5)">
              Low confidence scores indicate uncertain extraction, contradictory sources, or values outside expected physiological ranges.
            </p>
          </GlassCard>
        </div>
      </template>
    </div>
  </AppShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, defineComponent, h } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '~/components/layout/AppShell.vue'
import { useHeartTwinApi } from '~/composables/useHeartTwinApi'
import type { CaseRecord, EvaluationReport, SelfImproveResponse, WeaveInfo } from '~/types/api'
import type { MeasuredValue, ValueSource, RecoveryScenario, SourceMapEntry } from '~/types/heart'
import { sourceLabel } from '~/utils/units'

const route  = useRoute()
const caseId = computed(() => route.params.caseId as string)
const { getCase, getTrace, selfImprove } = useHeartTwinApi()

const TABS = [
  { key: 'overview',   label: 'Overview' },
  { key: 'files',      label: 'Files' },
  { key: 'extracted',  label: 'Evidence' },
  { key: 'state',      label: 'Cardiac State' },
  { key: 'operation',  label: 'Operation' },
  { key: 'recovery',   label: 'Recovery' },
  { key: 'trace',      label: 'Agent Trace' },
  { key: 'harness',    label: 'Harness' },
  { key: 'safety',     label: 'Safety' },
] as const

const SAFETY_ITEMS = [
  'No diagnosis provided',
  'Not for treatment decisions',
  'All outputs labeled as simulated',
  'Source confidence on every value',
  'Physiological bounds enforced',
  'Hard medical boundary enforced',
]

const activeTab = ref<string>('overview')
const loading   = ref(true)
const caseData  = ref<CaseRecord | null>(null)
const error     = ref<string | null>(null)
const traceEvents = ref<Array<Record<string, unknown>>>([])
const weaveInfo = ref<WeaveInfo | null>(null)
const selfImprovement = ref<SelfImproveResponse | null>(null)
const selfImproveLoading = ref(false)

onMounted(async () => {
  try {
    caseData.value = await getCase(caseId.value)
    const trace = await getTrace(caseId.value)
    traceEvents.value = trace.traces ?? []
    weaveInfo.value = trace.weave ?? null
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
})

const state        = computed(() => caseData.value?.state ?? null)
const simResult    = computed(() => caseData.value?.simulation_result ?? null)
const scenarios    = computed((): RecoveryScenario[] => caseData.value?.recovery_scenarios ?? [])
const stageResults = computed(() => caseData.value?.stage_results ?? [])
const files        = computed(() => caseData.value?.files ?? [])
const validatedFields = computed(
  (): Record<string, Record<string, unknown>> =>
    (caseData.value?.validated_fields ?? {}) as Record<string, Record<string, unknown>>,
)
const sourceMap = computed((): SourceMapEntry[] =>
  (state.value?.source_map ?? []) as SourceMapEntry[],
)
const warnings = computed((): string[] => state.value?.warnings ?? [])
const dqs      = computed((): number => state.value?.data_quality_score ?? 0)
const latestEvaluation = computed((): EvaluationReport | null => {
  const evaluator = [...stageResults.value].reverse().find(r => r.agent === 'evaluator_agent')
  return (evaluator?.outputs as unknown as EvaluationReport) ?? null
})

const statusDotColor = computed(() => {
  const s = caseData.value?.status ?? ''
  if (s === 'complete')  return '#4ade80'
  if (s === 'failed')    return '#f87171'
  if (s === 'running')   return '#60a5fa'
  return 'rgba(148,163,184,0.5)'
})

const nextAction = computed(() => {
  if (!caseData.value) return 'Load the case'
  if (!files.value.length && !state.value) return 'Upload cardiac files or enter manual vitals in the Lab'
  if (!state.value) return 'Run operation simulation using uploaded evidence'
  if (!simResult.value) return 'Run operation simulation using validated cardiac state'
  if (!scenarios.value.length) return 'Run recovery simulation to generate trajectory scenarios'
  return 'All simulation stages complete. Review results across tabs.'
})

function getMV(container: unknown, key: string): MeasuredValue | null {
  if (!container || typeof container !== 'object') return null
  return (container as Record<string, unknown>)[key] as MeasuredValue ?? null
}

const overviewMetrics = computed(() => {
  const m = (state.value?.measurements ?? {}) as Record<string, unknown>
  return [
    { label: 'Heart Rate',     value: getMV(m,'heart_rate_bpm')?.value,       unit: 'bpm',   source: getMV(m,'heart_rate_bpm')?.source as ValueSource,       confidence: getMV(m,'heart_rate_bpm')?.confidence,       decimals: 0,  showBar: false },
    { label: 'EF',             value: getMV(m,'ejection_fraction_pct')?.value, unit: '%',     source: getMV(m,'ejection_fraction_pct')?.source as ValueSource, confidence: getMV(m,'ejection_fraction_pct')?.confidence, showBar: true, barMin: 0, barMax: 80,  decimals: 1 },
    { label: 'Stroke Volume',  value: getMV(m,'stroke_volume_ml')?.value,      unit: 'mL',    source: getMV(m,'stroke_volume_ml')?.source as ValueSource,      confidence: getMV(m,'stroke_volume_ml')?.confidence,      decimals: 1,  showBar: false },
    { label: 'Cardiac Output', value: getMV(m,'cardiac_output_l_min')?.value,  unit: 'L/min', source: getMV(m,'cardiac_output_l_min')?.source as ValueSource,  confidence: getMV(m,'cardiac_output_l_min')?.confidence,  decimals: 2,  showBar: false },
    { label: 'SpO₂',          value: getMV(m,'oxygen_saturation_pct')?.value,  unit: '%',     source: getMV(m,'oxygen_saturation_pct')?.source as ValueSource, confidence: getMV(m,'oxygen_saturation_pct')?.confidence, decimals: 0,  showBar: true, barMin: 80, barMax: 100 },
    { label: 'EDV',            value: getMV(m,'edv_ml')?.value,                unit: 'mL',    source: getMV(m,'edv_ml')?.source as ValueSource,                confidence: getMV(m,'edv_ml')?.confidence,                decimals: 0,  showBar: false },
  ]
})

const opSummaryMetrics = computed(() => {
  const s = (simResult.value?.summary ?? {}) as Record<string, number>
  return [
    { label: 'HR',  value: s.heart_rate_bpm,      unit: 'bpm',   decimals: 0 },
    { label: 'EF',  value: s.ef_pct,               unit: '%',     decimals: 1 },
    { label: 'SV',  value: s.stroke_volume_ml,     unit: 'mL',    decimals: 1 },
    { label: 'CO',  value: s.cardiac_output_l_min, unit: 'L/min', decimals: 2 },
    { label: 'MAP', value: s.map_mmhg,             unit: 'mmHg',  decimals: 0 },
  ]
})

function buildFieldList(container: unknown): { label: string; mv: MeasuredValue }[] {
  if (!container || typeof container !== 'object') return []
  return Object.entries(container as Record<string, unknown>)
    .filter(([, v]) => v != null && typeof v === 'object' && 'value' in (v as object))
    .map(([k, v]) => ({ label: k, mv: v as MeasuredValue }))
}

const measurementFields = computed(() => buildFieldList(state.value?.measurements))
const epFields          = computed(() => buildFieldList(state.value?.electrophysiology))
const hdFields          = computed(() => buildFieldList(state.value?.hemodynamics))
const tissueFields      = computed(() => buildFieldList(state.value?.tissue_state))

function fileIcon(ct: string): string {
  if (ct === 'application/pdf') return '📄'
  if (ct.startsWith('image/'))  return '🖼️'
  if (ct === 'text/csv')        return '📊'
  return '📁'
}

function formatBytes(n: number): string {
  if (n < 1024)          return `${n} B`
  if (n < 1024 * 1024)   return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function formatEntry(entry: unknown): string {
  if (!entry || typeof entry !== 'object') return String(entry ?? '—')
  const e = entry as Record<string, unknown>
  if (e.value == null) return '—'
  const v = typeof e.value === 'number' ? (e.value as number).toFixed(2) : String(e.value)
  return `${v}${e.unit ? ' ' + e.unit : ''}`
}

async function runSelfImprove() {
  selfImproveLoading.value = true
  try {
    selfImprovement.value = await selfImprove(caseId.value)
    caseData.value = await getCase(caseId.value)
    const trace = await getTrace(caseId.value)
    traceEvents.value = trace.traces ?? []
    weaveInfo.value = trace.weave ?? selfImprovement.value.weave
  } catch (e) {
    error.value = String(e)
  } finally {
    selfImproveLoading.value = false
  }
}

const StateSection = defineComponent({
  props: {
    title:  { type: String, required: true },
    fields: { type: Array as () => { label: string; mv: MeasuredValue }[], required: true },
  },
  setup(props) {
    return () =>
      h('div', { class: 'glass-card p-4' }, [
        h('p', { class: 'panel-label mb-3' }, props.title),
        props.fields.length === 0
          ? h('p', { class: 'text-xs font-mono', style: 'color:rgba(148,163,184,0.4)' }, 'No data available')
          : h('div', { class: 'grid grid-cols-2 sm:grid-cols-3 gap-3' },
              props.fields.map(({ label, mv }) =>
                h('div', { class: 'space-y-0.5', key: label }, [
                  h('p', { class: 'text-[10px] font-mono uppercase tracking-wider', style: 'color:rgba(148,163,184,0.5)' }, label),
                  h('p', { class: 'text-sm font-mono text-white font-semibold tabular-nums' },
                    `${typeof mv.value === 'number' ? (mv.value as number).toFixed(2) : mv.value}${mv.unit ? ' ' + mv.unit : ''}`),
                  h('p', { class: 'text-[10px] font-mono', style: 'color:rgba(148,163,184,0.45)' },
                    `${sourceLabel(mv.source)} · ${Math.round(mv.confidence * 100)}%`),
                ]),
              ),
            ),
      ])
  },
})
</script>

<style scoped>
.glass-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.86), rgba(7, 17, 31, 0.70));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-md);
  box-shadow: 0 14px 44px rgba(0, 0, 0, 0.22);
}

.panel-label {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

.sim-label {
  display: inline-flex;
  align-items: center;
  padding: 0.18rem 0.55rem;
  color: var(--ht-cyan);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.26);
  border-radius: 999px;
}

.tab-bar {
  display: flex;
  overflow-x: auto;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  scrollbar-width: none;
}

.tab-bar::-webkit-scrollbar {
  display: none;
}

.tab-item-active,
.tab-item-inactive {
  padding: 0.58rem 0.9rem;
  margin-bottom: -1px;
  color: rgba(142, 160, 184, 0.70);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  transition: color 160ms ease, border-color 160ms ease, background 160ms ease;
}

.tab-item-active {
  color: #fff;
  background: rgba(255, 54, 95, 0.06);
  border-bottom-color: var(--ht-red);
}

.tab-item-inactive:hover {
  color: var(--ht-text);
}

.progress-track {
  height: 0.25rem;
  overflow: hidden;
  background: rgba(30, 41, 59, 0.88);
  border-radius: 999px;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 500ms ease;
}

.data-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.44rem 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.10);
}

.data-field:last-child {
  border-bottom: 0;
}

.data-key {
  color: rgba(142, 160, 184, 0.72);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.74rem;
}

.data-value {
  color: var(--ht-text);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.74rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.inline-warn,
.inline-error {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  padding: 0.4rem 0.62rem;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  border-radius: var(--ht-radius-sm);
}

.inline-warn {
  color: rgba(251, 191, 36, 0.92);
  background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.20);
}

.inline-error {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.10);
  border: 1px solid rgba(239, 68, 68, 0.22);
}

.badge-extracted {
  padding: 0.15rem 0.42rem;
  color: #7dd3fc;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.26);
  border-radius: var(--ht-radius-sm);
}

@media (prefers-reduced-motion: reduce) {
  .progress-fill,
  .tab-item-active,
  .tab-item-inactive {
    transition: none;
  }
}
</style>
