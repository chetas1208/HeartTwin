<template>
  <AppShell :show-nav="true">
    <div class="flex flex-col" style="height: calc(100vh - 3.5rem); overflow: hidden;">

      <!-- ══════════════════════════════════════════════
           LAB STATUS BAR
      ══════════════════════════════════════════════ -->
      <div class="lab-statusbar shrink-0">
        <!-- Case ID -->
        <div class="lab-statusbar-item">
          <span style="color:rgba(148,163,184,0.4)">CASE</span>
          <span class="font-semibold" :class="caseStore.caseId ? 'text-cardiac-electric' : 'text-cardiac-muted/40'">
            {{ caseStore.caseId ? caseStore.caseId.slice(0, 12) + '…' : 'none' }}
          </span>
        </div>

        <!-- Step progress (desktop) -->
        <div class="flex-1 hidden md:flex items-center min-w-0">
          <StepProgress :steps="flowSteps" class="w-full" @step-click="() => {}" />
        </div>

        <div class="flex items-center gap-2 ml-auto shrink-0">
          <!-- Data quality -->
          <div v-if="caseStore.dataQualityScore !== null" class="lab-statusbar-item">
            <span style="color:rgba(148,163,184,0.4)">DQ</span>
            <span class="font-semibold tabular-nums" :class="dqColor">
              {{ Math.round((caseStore.dataQualityScore ?? 0) * 100) }}%
            </span>
          </div>

          <!-- Loading indicator -->
          <div v-if="caseStore.loading" class="flex items-center gap-1.5 lab-statusbar-item" style="border-color:rgba(26,111,255,0.35);">
            <svg class="w-2.5 h-2.5 animate-spin" style="color:#7bb8ff" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            <span style="color:#7bb8ff">{{ caseStore.currentStage || 'Processing' }}</span>
          </div>

          <!-- Safety chip -->
          <div class="hidden lg:flex safety-chip">
            <svg class="w-2.5 h-2.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
            </svg>
            Sim Only
          </div>
        </div>
      </div>

      <!-- Medical boundary banner -->
      <div class="px-3 pt-1.5 pb-0.5 shrink-0">
        <MedicalBoundaryBanner :dismissible="true" />
      </div>

      <!-- ══════════════════════════════════════════════
           MAIN 3-COLUMN LAYOUT
      ══════════════════════════════════════════════ -->
      <div class="flex flex-1 min-h-0">

        <!-- ────────────────────────────────────────
             LEFT PANEL: Inputs & Controls
        ──────────────────────────────────────────── -->
        <aside
          class="w-72 xl:w-80 shrink-0 flex flex-col overflow-y-auto"
          style="background:rgba(7,20,40,0.97); border-right:1px solid rgba(16,42,80,0.75);"
          aria-label="Case inputs and controls"
        >
          <div class="p-3 space-y-4 flex-1">

            <!-- Section: Case Setup -->
            <section>
              <div class="flex items-center justify-between mb-2">
                <h2 class="panel-label">Case Setup</h2>
                <button
                  v-if="!caseStore.caseId"
                  class="action-btn action-btn--ready text-[10px] px-2 py-1 w-auto"
                  style="font-size:10px;"
                  @click="handleCreateCase"
                >
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15"/>
                  </svg>
                  New Case
                </button>
                <span v-else class="text-[10px] font-mono" style="color:rgba(74,222,128,0.7)">
                  ✓ Active
                </span>
              </div>

              <!-- Case ID display -->
              <div v-if="caseStore.caseId" class="glass-card px-3 py-2 mb-3">
                <div class="flex items-center justify-between">
                  <span class="text-[10px] font-mono" style="color:rgba(148,163,184,0.45)">Case ID</span>
                  <NuxtLink
                    :to="`/case/${caseStore.caseId}`"
                    class="text-[10px] font-mono transition-colors"
                    style="color:rgba(0,212,255,0.7);"
                  >
                    View Case →
                  </NuxtLink>
                </div>
                <p class="text-xs font-mono text-white mt-0.5 truncate">{{ caseStore.caseId }}</p>
              </div>
            </section>

            <!-- Section: File Upload -->
            <section>
              <h2 class="panel-label mb-2">Evidence Upload</h2>
              <FileDropzone :uploading="fileUpload.uploading.value" @files="handleFiles" />
              <UploadedFileList v-if="caseStore.files.length" :files="caseStore.files" class="mt-2" />
            </section>

            <!-- Section: Manual Vitals -->
            <section>
              <h2 class="panel-label mb-2">Manual Vitals</h2>
              <ManualVitalsForm @submit="handleVitals" />
            </section>

            <!-- System check -->
            <SystemCheckPanel />

            <!-- Section: Action Flow -->
            <section>
              <h2 class="panel-label mb-2">Simulation Flow</h2>
              <div class="space-y-1.5">

                <!-- Create Case -->
                <ActionButton
                  label="1. Create Case"
                  icon="plus"
                  :state="!caseStore.caseId ? 'ready' : 'done'"
                  :loading="false"
                  reason=""
                  @click="handleCreateCase"
                />

                <!-- Extract Evidence -->
                <ActionButton
                  label="2. Extract Evidence"
                  icon="extract"
                  :state="extractState"
                  :loading="caseStore.loading && caseStore.currentStage === 'extract'"
                  :reason="extractDisabledReason"
                  @click="runExtract"
                />

                <!-- Operate -->
                <ActionButton
                  label="3. Run Operation"
                  icon="heart"
                  :state="operateState"
                  :loading="caseStore.loading && caseStore.currentStage === 'operate'"
                  :reason="operateDisabledReason"
                  @click="runOperate"
                />

                <!-- Simulate Recovery -->
                <ActionButton
                  label="4. Simulate Recovery"
                  icon="chart"
                  :state="recoveryState"
                  :loading="caseStore.loading && caseStore.currentStage === 'recovery'"
                  :reason="recoveryDisabledReason"
                  @click="runRecovery"
                />
              </div>
            </section>

            <!-- Operating environment (only show when case ready) -->
            <section v-if="caseStore.caseId">
              <OperatingEnvironmentPanel
                :disabled="!caseStore.caseId || caseStore.loading"
                @run="runOperateWithEnv"
              />
            </section>

            <!-- Error display -->
            <div
              v-if="caseStore.error"
              class="inline-error"
              role="alert"
            >
              <svg class="w-3.5 h-3.5 shrink-0 mt-px" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
              </svg>
              {{ caseStore.error }}
            </div>
          </div>
        </aside>

        <!-- ────────────────────────────────────────
             CENTER: 3D HeartTwin Scene
        ──────────────────────────────────────────── -->
        <main
          class="flex-1 flex flex-col min-w-0 overflow-hidden relative"
          style="background:rgba(3,13,26,0.98);"
          aria-label="HeartTwin 3D visualization"
        >
          <!-- ECG grid overlay -->
          <div class="absolute inset-0 ecg-grid-fine opacity-30 pointer-events-none" aria-hidden="true" />

          <!-- Scan line animation -->
          <div
            class="absolute inset-x-0 h-px pointer-events-none animate-scan"
            style="background:linear-gradient(90deg, transparent, rgba(227,27,27,0.12), transparent); top:10%;"
            aria-hidden="true"
          />

          <!-- 3D Scene -->
          <div class="flex-1 relative">
            <ClientOnly>
              <HeartTwinScene
                v-if="simState"
                :state="caseStore.state"
                :visualization="simState"
                :operating-mode="caseStore.state?.operating_environment?.mode ?? 'rest'"
                :show-blood-flow="true"
                :show-electrical-overlay="true"
                :show-damage-zone="true"
              />

              <!-- Empty state — awaiting cardiac state -->
              <div v-else class="absolute inset-0 flex flex-col items-center justify-center gap-5">
                <div class="relative">
                  <div
                    class="w-20 h-20 rounded-full flex items-center justify-center"
                    style="background:rgba(227,27,27,0.06); border:1px solid rgba(227,27,27,0.1);"
                  >
                    <svg class="w-10 h-10 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z"/>
                    </svg>
                  </div>
                  <div
                    class="absolute inset-0 rounded-full animate-ping"
                    style="background:rgba(227,27,27,0.04); animation-duration:2.5s;"
                    aria-hidden="true"
                  />
                </div>

                <svg class="w-48 opacity-10" height="30" viewBox="0 0 200 30" aria-hidden="true">
                  <polyline
                    points="0,15 40,15 50,2 60,28 70,15 110,15 118,8 128,22 138,15 200,15"
                    stroke="#e31b1b"
                    stroke-width="1.5"
                    fill="none"
                  />
                </svg>

                <div class="text-center max-w-xs space-y-2">
                  <p class="text-sm font-mono font-semibold" style="color:rgba(241,245,249,0.5)">Awaiting cardiac state</p>
                  <p class="text-xs font-mono" style="color:rgba(148,163,184,0.35)">
                    Enter vitals or upload cardiac files,<br>then run Extract → Operate.
                  </p>
                </div>
              </div>
            </ClientOnly>
          </div>

          <!-- Bottom metrics bar -->
          <div
            v-if="simState"
            class="shrink-0 px-4 py-2"
            style="border-top:1px solid rgba(16,42,80,0.7); background:rgba(7,20,40,0.97);"
          >
            <div class="flex gap-3 overflow-x-auto pb-0.5">
              <MetricCard
                v-for="m in summaryMetrics"
                :key="m.label"
                :label="m.label"
                :value="m.value"
                :unit="m.unit"
                :decimals="m.decimals ?? 1"
                :compact="true"
                class="min-w-[80px] shrink-0"
              />
            </div>
          </div>
        </main>

        <!-- ────────────────────────────────────────
             RIGHT PANEL: Cardiac State & Metrics
        ──────────────────────────────────────────── -->
        <aside
          class="w-72 xl:w-80 shrink-0 flex flex-col overflow-y-auto"
          style="background:rgba(7,20,40,0.97); border-left:1px solid rgba(16,42,80,0.75);"
          aria-label="Cardiac state and metrics"
        >
          <div class="p-3 space-y-4">

            <!-- Data Quality -->
            <section v-if="caseStore.dataQualityScore !== null">
              <h2 class="panel-label mb-2">Data Quality</h2>
              <div class="glass-card px-3 py-2.5 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-mono text-white">{{ dqLabel }}</span>
                  <span class="text-xs font-mono font-semibold tabular-nums" :class="dqColor">
                    {{ Math.round((caseStore.dataQualityScore ?? 0) * 100) }}%
                  </span>
                </div>
                <div class="progress-track">
                  <div
                    class="progress-fill"
                    :class="dqFillClass"
                    :style="{ width: `${Math.round((caseStore.dataQualityScore ?? 0) * 100)}%` }"
                  />
                </div>
              </div>
            </section>

            <!-- Cardiac State Metrics -->
            <section v-if="caseStore.state">
              <h2 class="panel-label mb-2">Cardiac State</h2>
              <div>
                <div
                  v-for="m in cardiacStateMetrics"
                  :key="m.field"
                  class="data-field"
                >
                  <div class="flex-1 min-w-0">
                    <p class="data-key">{{ m.label }}</p>
                    <p class="text-sm font-mono font-semibold text-white/90 tabular-nums">
                      {{ m.value != null
                        ? `${typeof m.value === 'number' ? m.value.toFixed(m.decimals ?? 1) : m.value}${m.unit ? ` ${m.unit}` : ''}`
                        : '—' }}
                    </p>
                  </div>
                  <SourceConfidenceBadge
                    v-if="m.source && m.confidence != null"
                    :source="m.source"
                    :confidence="m.confidence"
                    class="shrink-0"
                  />
                  <span
                    v-else-if="m.value == null"
                    class="text-[10px] font-mono shrink-0"
                    style="color:rgba(148,163,184,0.35)"
                  >
                    Unavailable
                  </span>
                </div>
              </div>
            </section>

            <!-- Empty state -->
            <section v-if="!caseStore.state && !caseStore.loading">
              <EmptyState
                title="No cardiac state"
                description="Run extraction and operation to build the canonical cardiac state."
                icon="heart"
                :compact="true"
              />
            </section>

            <!-- Warnings -->
            <section v-if="caseStore.warnings.length">
              <h2 class="panel-label mb-2">Warnings</h2>
              <div class="space-y-1">
                <div
                  v-for="w in caseStore.warnings.slice(0, 5)"
                  :key="w"
                  class="inline-warn"
                >
                  <svg class="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
                  </svg>
                  {{ w }}
                </div>
                <p v-if="caseStore.warnings.length > 5" class="text-[10px] font-mono" style="color:rgba(148,163,184,0.4)">
                  +{{ caseStore.warnings.length - 5 }} more
                </p>
              </div>
            </section>

            <!-- Agent Trace (compact) -->
            <section v-if="caseStore.stageResults.length">
              <div class="flex items-center justify-between mb-2">
                <h2 class="panel-label">Agent Trace</h2>
                <NuxtLink
                  v-if="caseStore.caseId"
                  :to="`/case/${caseStore.caseId}`"
                  class="text-[10px] font-mono transition-colors"
                  style="color:rgba(0,212,255,0.6);"
                >
                  Full →
                </NuxtLink>
              </div>
              <AgentTraceTimeline :responses="caseStore.stageResults" :compact="true" />
            </section>
          </div>
        </aside>
      </div>

      <!-- ══════════════════════════════════════════════
           BOTTOM PANEL: Charts + Trace (tabbed)
      ══════════════════════════════════════════════ -->
      <div
        v-if="simState || caseStore.stageResults.length"
        class="shrink-0"
        :style="{
          height: bottomTab === 'harness' ? '360px' : '220px',
          borderTop: '1px solid rgba(16,42,80,0.7)',
          background: 'rgba(3,13,26,0.98)',
        }"
      >
        <!-- Tab bar -->
        <div class="tab-bar px-3" role="tablist" aria-label="Analysis views">
          <button
            v-for="tab in BOTTOM_TABS"
            :key="tab.key"
            role="tab"
            :aria-selected="bottomTab === tab.key"
            :class="bottomTab === tab.key ? 'tab-item-active' : 'tab-item-inactive'"
            @click="bottomTab = tab.key"
          >
            {{ tab.label }}
            <span
              v-if="tab.key === 'warnings' && caseStore.warnings.length"
              class="ml-1 text-[9px] px-1 py-0.5 rounded-full"
              style="background:rgba(245,158,11,0.2); color:#fbbf24;"
            >
              {{ caseStore.warnings.length }}
            </span>
          </button>
        </div>

        <!-- Tab panels -->
        <div :class="bottomTab === 'harness' ? 'h-[321px]' : 'h-[181px]'" class="flex" role="tabpanel">

          <!-- ECG -->
          <template v-if="bottomTab === 'ecg'">
            <div class="flex-1 relative">
              <ClientOnly>
                <EcgTrace
                  :time-ms="ecgData?.time_ms"
                  :pressure="ecgData?.lv_pressure_mmhg"
                  :heart-rate-bpm="simState?.summary?.heart_rate_bpm"
                />
              </ClientOnly>
              <div v-if="!ecgData" class="absolute inset-0 flex items-center justify-center">
                <EmptyState
                  title="No ECG data"
                  description="Run operation to generate cardiac cycle data."
                  icon="chart"
                  :compact="true"
                />
              </div>
              <div class="absolute bottom-1.5 left-2 sim-label text-[9px] py-0.5 px-1.5">
                Simulated visualization · not for diagnosis or treatment decisions
              </div>
            </div>
          </template>

          <!-- PV Loop -->
          <template v-else-if="bottomTab === 'pv'">
            <div class="flex-1 relative">
              <ClientOnly>
                <PressureVolumeLoop :pv-loop="pvData" />
              </ClientOnly>
              <div v-if="!pvData" class="absolute inset-0 flex items-center justify-center">
                <EmptyState
                  title="No PV loop data"
                  description="Run operation to compute the pressure-volume loop."
                  icon="chart"
                  :compact="true"
                />
              </div>
              <div class="absolute bottom-1.5 left-2 sim-label text-[9px] py-0.5 px-1.5">
                Deterministic hemodynamics model
              </div>
            </div>
          </template>

          <!-- Recovery -->
          <template v-else-if="bottomTab === 'recovery'">
            <div class="flex-1 relative">
              <ClientOnly>
                <RecoveryTimeline :scenarios="caseStore.recoveryScenarios" />
              </ClientOnly>
              <div v-if="!caseStore.recoveryScenarios?.length" class="absolute inset-0 flex items-center justify-center">
                <EmptyState
                  title="No recovery scenarios"
                  description="Run recovery simulation to see bounded trajectories with uncertainty bands."
                  icon="chart"
                  :compact="true"
                />
              </div>
              <div class="absolute bottom-1.5 left-2 sim-label text-[9px] py-0.5 px-1.5">
                Bounded model scenarios · not for diagnosis or treatment decisions
              </div>
            </div>
          </template>

          <!-- Agent Trace -->
          <template v-else-if="bottomTab === 'trace'">
            <div class="flex-1 overflow-y-auto px-4 py-3">
              <AgentTraceTimeline
                v-if="caseStore.stageResults.length"
                :responses="caseStore.stageResults"
              />
              <EmptyState
                v-else
                title="No trace available"
                description="Run extraction or operation to see the agent decision trace."
                icon="trace"
                :compact="true"
              />
            </div>
          </template>

          <!-- Harness -->
          <template v-else-if="bottomTab === 'harness'">
            <div class="flex-1 overflow-y-auto px-4 py-3">
              <HarnessPanel
                :responses="caseStore.stageResults"
                :evaluation="caseStore.evaluationReport"
                :weave="caseStore.weaveInfo"
                :traces="caseStore.traceEvents"
                :has-recovery="caseStore.hasRecovery"
                :self-improvement="caseStore.selfImprovementResult"
                :loading="caseStore.loading"
                @improve="runSelfImprove"
              />
            </div>
          </template>

          <!-- Warnings -->
          <template v-else-if="bottomTab === 'warnings'">
            <div class="flex-1 overflow-y-auto px-4 py-3 space-y-2">
              <div v-if="!caseStore.warnings.length" class="h-full flex items-center justify-center">
                <EmptyState
                  title="No warnings"
                  description="All extracted values are within expected physiological bounds."
                  icon="check"
                  :compact="true"
                />
              </div>
              <div
                v-for="w in caseStore.warnings"
                :key="w"
                class="inline-warn"
              >
                <svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
                </svg>
                {{ w }}
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref } from 'vue'
import AppShell from '~/components/layout/AppShell.vue'
import type { ManualVitals } from '~/utils/schemas'
import type { OperatingEnvironment, MeasuredValue, ValueSource } from '~/types/heart'
import { useCaseStore } from '~/stores/case'
import { useFileUpload } from '~/composables/useFileUpload'
import { dataQualityLabel, dataQualityColor } from '~/utils/units'
import type { Step } from '~/components/layout/StepProgress.vue'

const caseStore = useCaseStore()
const fileUpload = useFileUpload()

const userVitals = ref<ManualVitals | null>(null)
const bottomTab  = ref<string>('ecg')

const BOTTOM_TABS = [
  { key: 'ecg',      label: 'ECG' },
  { key: 'pv',       label: 'PV Loop' },
  { key: 'recovery', label: 'Recovery' },
  { key: 'trace',    label: 'Agent Trace' },
  { key: 'harness',  label: 'Harness' },
  { key: 'warnings', label: 'Warnings' },
]

// ── Flow step progress ───────────────────────────────────────
const flowSteps = computed((): Step[] => [
  {
    key: 'case',
    label: 'Case',
    status: caseStore.caseId ? 'done' : 'ready',
  },
  {
    key: 'evidence',
    label: 'Evidence',
    status: !caseStore.caseId
      ? 'idle'
      : caseStore.hasExtracted
        ? 'done'
        : caseStore.loading && caseStore.currentStage === 'extract'
          ? 'active'
          : 'ready',
  },
  {
    key: 'state',
    label: 'State',
    status: caseStore.state ? 'done' : !caseStore.hasExtracted ? 'idle' : 'ready',
  },
  {
    key: 'operation',
    label: 'Operation',
    status: caseStore.simulationResult
      ? 'done'
      : !caseStore.state
        ? 'idle'
        : caseStore.loading && caseStore.currentStage === 'operate'
          ? 'active'
          : 'ready',
  },
  {
    key: 'recovery',
    label: 'Recovery',
    status: caseStore.recoveryScenarios?.length
      ? 'done'
      : !caseStore.simulationResult
        ? 'idle'
        : caseStore.loading && caseStore.currentStage === 'recovery'
          ? 'active'
          : 'ready',
  },
  {
    key: 'trace',
    label: 'Trace',
    status: caseStore.stageResults.length ? 'done' : 'idle',
  },
])

// ── Button states ────────────────────────────────────────────
type ActionState = 'idle' | 'ready' | 'active' | 'done' | 'warning' | 'error'

const extractState = computed((): ActionState => {
  if (!caseStore.caseId) return 'idle'
  if (caseStore.loading && caseStore.currentStage === 'extract') return 'active'
  if (caseStore.hasExtracted) return 'done'
  return 'ready'
})
const extractDisabledReason = computed(() => {
  if (!caseStore.caseId) return 'Create a case first'
  if (caseStore.loading) return 'Processing…'
  return ''
})

const operateState = computed((): ActionState => {
  if (!caseStore.hasExtracted && !userVitals.value) return 'idle'
  if (caseStore.loading && caseStore.currentStage === 'operate') return 'active'
  if (caseStore.simulationResult) return 'done'
  return 'ready'
})
const operateDisabledReason = computed(() => {
  if (!caseStore.caseId) return 'Create a case first'
  if (!caseStore.hasExtracted && !userVitals.value) return 'Extract evidence or enter manual vitals first'
  if (caseStore.loading) return 'Processing…'
  return ''
})

const recoveryState = computed((): ActionState => {
  if (!caseStore.simulationResult) return 'idle'
  if (caseStore.loading && caseStore.currentStage === 'recovery') return 'active'
  if (caseStore.recoveryScenarios?.length) return 'done'
  return 'ready'
})
const recoveryDisabledReason = computed(() => {
  if (!caseStore.simulationResult) return 'Run operation simulation first'
  if (caseStore.loading) return 'Processing…'
  return ''
})

// ── Derived ──────────────────────────────────────────────────
const simState  = computed(() => caseStore.simulationResult)
const pvData    = computed(() => simState.value?.pv_loop ?? null)
const ecgData   = computed(() => simState.value?.cardiac_cycle ?? null)

const dqLabel     = computed(() => dataQualityLabel(caseStore.dataQualityScore ?? 0))
const dqColor     = computed(() => dataQualityColor(caseStore.dataQualityScore ?? 0))
const dqFillClass = computed(() => {
  const s = caseStore.dataQualityScore ?? 0
  if (s >= 0.75) return 'bg-cardiac-safe'
  if (s >= 0.50) return 'bg-cardiac-warn'
  if (s >= 0.25) return 'bg-cardiac-pulse'
  return 'bg-cardiac-red'
})

const summaryMetrics = computed(() => {
  const s = simState.value?.summary
  if (!s) return []
  return [
    { label: 'HR',  value: s.heart_rate_bpm,       unit: 'bpm',   decimals: 0 },
    { label: 'EF',  value: s.ef_pct,                unit: '%',     decimals: 1 },
    { label: 'SV',  value: s.stroke_volume_ml,      unit: 'mL',    decimals: 1 },
    { label: 'CO',  value: s.cardiac_output_l_min,  unit: 'L/min', decimals: 2 },
    { label: 'MAP', value: s.map_mmhg,              unit: 'mmHg',  decimals: 0 },
  ]
})

function mvField(mv: MeasuredValue | null | undefined, label: string, unit: string, decimals = 1) {
  return {
    field: label,
    label,
    unit,
    value: mv?.value ?? null,
    source: (mv?.source ?? null) as ValueSource | null,
    confidence: mv?.confidence ?? null,
    decimals,
  }
}

const cardiacStateMetrics = computed(() => {
  const st = caseStore.state
  if (!st) return []
  const m  = st.measurements
  const hd = st.hemodynamics
  const ts = st.tissue_state
  return [
    mvField(m.heart_rate_bpm,        'Heart Rate',    'bpm',   0),
    mvField(m.ejection_fraction_pct, 'EF',            '%',     1),
    mvField(m.stroke_volume_ml,      'Stroke Vol.',   'mL',    1),
    mvField(m.cardiac_output_l_min,  'Cardiac Out.',  'L/min', 2),
    mvField(m.edv_ml,                'EDV',           'mL',    0),
    mvField(m.esv_ml,                'ESV',           'mL',    0),
    mvField(hd.preload_index,        'Preload',       'idx',   3),
    mvField(hd.afterload_index,      'Afterload',     'idx',   3),
    mvField(hd.contractility_index,  'Contractility', 'idx',   3),
    mvField(ts.oxygen_delivery_index,'O₂ Delivery',  'idx',   3),
    mvField(ts.inflammation_index,   'Inflammation',  'idx',   3),
    mvField(ts.scar_fraction,        'Scar Fraction', 'frac',  3),
  ]
})

// ── Action button component ──────────────────────────────────
const ActionButton = defineComponent({
  props: {
    label:   { type: String, required: true },
    icon:    { type: String, default: 'default' },
    state:   { type: String as () => ActionState, default: 'idle' },
    loading: { type: Boolean, default: false },
    reason:  { type: String, default: '' },
  },
  emits: ['click'],
  setup(ap, { emit: ae }) {
    const ICONS: Record<string, string> = {
      plus:    'M12 4.5v15m7.5-7.5h-15',
      extract: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
      heart:   'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z',
      chart:   'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
    }
    const DOT_COLORS: Record<string, string> = {
      idle: 'rgba(148,163,184,0.2)', ready: 'rgba(148,163,184,0.6)',
      active: '#3b82f6', done: '#4ade80', warning: '#fbbf24', error: '#f87171',
    }
    const STATUS_CHARS: Record<string, string> = {
      done: '✓', warning: '!', error: '✕',
    }

    return () => {
      const s = ap.state as ActionState
      const isDisabled = s === 'idle' || ap.loading
      return h('div', [
        h('button', {
          class: `action-btn action-btn--${s}`,
          disabled: isDisabled,
          title: ap.reason || undefined,
          onClick: () => !isDisabled && ae('click'),
        }, [
          h('div', {
            class: 'w-1.5 h-1.5 rounded-full shrink-0',
            style: `background:${DOT_COLORS[s] ?? DOT_COLORS.idle}`,
            'aria-hidden': 'true',
          }),
          h('svg', {
            class: 'w-3.5 h-3.5 shrink-0',
            fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.5',
            'aria-hidden': 'true',
          }, [h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d: ICONS[ap.icon] ?? ICONS.plus })]),
          h('span', { class: 'flex-1' }, ap.label),
          ap.loading
            ? h('svg', { class: 'w-3.5 h-3.5 animate-spin shrink-0', fill: 'none', viewBox: '0 0 24 24', 'aria-hidden': 'true' }, [
                h('circle', { class: 'opacity-25', cx: '12', cy: '12', r: '10', stroke: 'currentColor', 'stroke-width': '4' }),
                h('path', { class: 'opacity-75', fill: 'currentColor', d: 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z' }),
              ])
            : STATUS_CHARS[s]
              ? h('span', { class: 'text-[10px] font-mono shrink-0' }, STATUS_CHARS[s])
              : null,
        ]),
        ap.reason && isDisabled && !ap.loading
          ? h('p', { class: 'text-[10px] font-mono mt-0.5 px-1', style: 'color:rgba(148,163,184,0.35)' }, ap.reason)
          : null,
      ])
    }
  },
})

// ── Handlers ─────────────────────────────────────────────────
function handleVitals(vitals: ManualVitals) { userVitals.value = vitals }

async function handleCreateCase() {
  if (!caseStore.caseId) await caseStore.createCase()
}

async function handleFiles(files: File[]) {
  if (!caseStore.caseId) await caseStore.createCase()
  await fileUpload.uploadFiles(caseStore.caseId!, files)
}

async function runExtract() {
  if (!caseStore.caseId) await caseStore.createCase()
  await caseStore.extract(caseStore.files.map(f => f.file_id), userVitals.value ? _vitalsToRecord(userVitals.value) : {})
}

async function runOperate() {
  if (caseStore.caseId) await caseStore.operate()
}

async function runOperateWithEnv(env: Partial<OperatingEnvironment>) {
  if (caseStore.caseId) await caseStore.operate(env)
}

async function runRecovery() {
  if (caseStore.caseId) await caseStore.simulateRecovery()
}

async function runSelfImprove() {
  if (caseStore.caseId) await caseStore.improveHarnessRun()
}

function _vitalsToRecord(v: ManualVitals): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (v.heart_rate_bpm != null)        out.heart_rate_bpm        = v.heart_rate_bpm
  if (v.systolic_bp_mmhg != null)      out.systolic_bp_mmhg      = v.systolic_bp_mmhg
  if (v.diastolic_bp_mmhg != null)     out.diastolic_bp_mmhg     = v.diastolic_bp_mmhg
  if (v.edv_ml != null)                out.edv_ml                = v.edv_ml
  if (v.esv_ml != null)                out.esv_ml                = v.esv_ml
  if (v.ejection_fraction_pct != null) out.ejection_fraction_pct = v.ejection_fraction_pct
  if (v.troponin_ng_l != null)         out.troponin_ng_l         = v.troponin_ng_l
  if (v.bnp_pg_ml != null)             out.bnp_pg_ml             = v.bnp_pg_ml
  if (v.oxygen_saturation_pct != null) out.oxygen_saturation_pct = v.oxygen_saturation_pct
  if (v.age_years != null)             out.age_years             = v.age_years
  if (v.sex)                           out.sex                   = v.sex
  if (v.height_cm != null)             out.height_cm             = v.height_cm
  if (v.weight_kg != null)             out.weight_kg             = v.weight_kg
  return out
}
</script>

<style scoped>
.lab-statusbar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.4rem 1rem;
  color: rgba(142, 160, 184, 0.70);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  background:
    linear-gradient(180deg, rgba(3, 7, 17, 0.98), rgba(7, 17, 31, 0.94));
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
}

.lab-statusbar-item {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.2rem 0.5rem;
  background: rgba(10, 20, 35, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: var(--ht-radius-sm);
}

.safety-chip,
.sim-label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.22rem 0.55rem;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  border-radius: 999px;
}

.safety-chip {
  color: rgba(251, 191, 36, 0.86);
  background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.22);
}

.sim-label {
  color: var(--ht-cyan);
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.26);
}

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
  padding: 0.42rem 0;
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
  padding: 0.55rem 0.875rem;
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

:deep(.action-btn) {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.62rem;
  padding: 0.62rem 0.75rem;
  border: 1px solid transparent;
  border-radius: var(--ht-radius-sm);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.76rem;
  font-weight: 700;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

:deep(.action-btn--idle) {
  color: rgba(142, 160, 184, 0.40);
  cursor: not-allowed;
  background: rgba(30, 41, 59, 0.35);
  border-color: rgba(148, 163, 184, 0.10);
}

:deep(.action-btn--ready) {
  color: rgba(226, 232, 240, 0.82);
  background: rgba(10, 20, 35, 0.72);
  border-color: rgba(148, 163, 184, 0.16);
}

:deep(.action-btn--ready:hover) {
  border-color: rgba(255, 54, 95, 0.40);
  box-shadow: var(--ht-shadow-glow-red);
}

:deep(.action-btn--active) {
  color: #fff;
  background: rgba(56, 189, 248, 0.13);
  border-color: rgba(56, 189, 248, 0.36);
}

:deep(.action-btn--done) {
  color: #86efac;
  background: rgba(34, 197, 94, 0.10);
  border-color: rgba(34, 197, 94, 0.28);
}

@media (prefers-reduced-motion: reduce) {
  .progress-fill,
  .tab-item-active,
  .tab-item-inactive,
  :deep(.action-btn) {
    transition: none;
  }
}
</style>
