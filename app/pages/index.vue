<template>
  <AppShell :show-nav="true">

    <!-- ══════════════════════════════════════════
         HERO
    ══════════════════════════════════════════ -->
    <section class="relative min-h-[94vh] flex flex-col items-center justify-center px-6 overflow-hidden">

      <!-- Fine ECG grid background -->
      <div class="absolute inset-0 ecg-grid-fine opacity-40 pointer-events-none" aria-hidden="true" />

      <!-- Animated ECG waveform baseline -->
      <div class="absolute inset-x-0 bottom-[28%] overflow-hidden pointer-events-none" style="opacity:0.12;" aria-hidden="true">
        <svg class="w-full" height="50" viewBox="0 0 1440 50" preserveAspectRatio="none">
          <polyline
            points="0,25 100,25 120,4 140,46 160,25 260,25 280,9 300,41 320,25 420,25 440,12 460,38 480,25 580,25 600,7 620,43 640,25 740,25 760,14 780,36 800,25 900,25 920,5 940,45 960,25 1060,25 1080,18 1100,32 1120,25 1220,25 1240,10 1260,40 1280,25 1380,25 1400,22 1420,28 1440,25"
            stroke="#e31b1b"
            stroke-width="1.5"
            fill="none"
            class="animate-ecg-line"
          />
        </svg>
      </div>

      <!-- Content -->
      <div class="relative z-10 text-center max-w-4xl mx-auto">

        <!-- Classification chip -->
        <div
          class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-10 text-xs font-mono"
          style="background:rgba(10,31,58,0.9); border:1px solid rgba(227,27,27,0.2); color:rgba(148,163,184,0.7);"
        >
          <span class="w-1.5 h-1.5 rounded-full bg-cardiac-red animate-pulse shrink-0" aria-hidden="true" />
          Educational Simulation · Not for Clinical Use · v2.0
        </div>

        <!-- Headline -->
        <h1 class="text-5xl md:text-6xl lg:text-7xl font-bold tracking-tight mb-6 leading-tight text-white">
          Build a living simulation
          <span class="block text-gradient-red mt-1">of heart function.</span>
        </h1>

        <!-- Sub-headline -->
        <p class="text-lg md:text-xl leading-relaxed mb-8 max-w-2xl mx-auto font-light" style="color:rgba(148,163,184,0.7);">
          HeartTwin Lab turns cardiac reports, ECG data, imaging, and vitals
          into an explainable cardiac operation and recovery simulator.
          Every value shows its source, confidence, and extraction method.
        </p>

        <!-- Floating metric chips -->
        <div class="flex flex-wrap justify-center gap-2 mb-10" role="list" aria-label="Example simulation metrics">
          <div
            v-for="(chip, i) in METRIC_CHIPS"
            :key="chip.key"
            class="flex items-center gap-2 px-3 py-1.5 rounded-full transition-colors duration-200 animate-chip-in"
            :style="{
              background: 'rgba(10,31,58,0.8)',
              border: '1px solid rgba(16,42,80,0.8)',
              animationDelay: `${i * 60}ms`,
            }"
            role="listitem"
          >
            <span class="text-xs font-mono" style="color:rgba(148,163,184,0.6)">{{ chip.key }}</span>
            <span class="text-xs font-mono font-bold text-white tabular-nums">{{ chip.val }}</span>
            <span class="text-xs font-mono" style="color:rgba(148,163,184,0.45)">{{ chip.unit }}</span>
          </div>
        </div>

        <!-- CTA buttons -->
        <div class="flex flex-col sm:flex-row gap-3 justify-center">
          <NuxtLink
            to="/lab"
            class="btn-primary text-base px-8 py-3 inline-flex items-center justify-center gap-2 rounded-xl"
            style="box-shadow: 0 0 20px rgba(227,27,27,0.25);"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/>
            </svg>
            Open Lab
          </NuxtLink>
          <a
            href="#safety"
            class="btn-secondary text-base px-8 py-3 inline-flex items-center justify-center gap-2 rounded-xl"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
            </svg>
            View Safety Boundary
          </a>
        </div>

        <p class="text-xs font-mono mt-8" style="color:rgba(148,163,184,0.35); letter-spacing: 0.05em;">
          Educational simulation only · Not for diagnosis or treatment decisions
        </p>
      </div>

      <!-- Scroll hint -->
      <div class="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 opacity-25" aria-hidden="true">
        <span class="text-xs font-mono tracking-widest" style="color:rgba(148,163,184,0.6)">SCROLL</span>
        <svg class="w-4 h-4 animate-bounce" style="color:rgba(148,163,184,0.6)" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </div>
    </section>

    <!-- ══════════════════════════════════════════
         HOW IT WORKS
    ══════════════════════════════════════════ -->
    <section class="max-w-5xl mx-auto px-6 py-24">
      <div class="text-center mb-16">
        <span class="panel-label">Pipeline</span>
        <h2 class="text-3xl md:text-4xl font-bold text-white mt-3">
          From data to simulation in seconds
        </h2>
        <p class="text-sm leading-relaxed mt-3 max-w-lg mx-auto" style="color:rgba(148,163,184,0.6)">
          An 8-agent deterministic pipeline processes every input, validates every value,
          and builds a canonical cardiac state you can operate and simulate.
        </p>
      </div>

      <!-- Desktop horizontal flow -->
      <div class="hidden md:flex items-start gap-0 relative">
        <!-- Background connector rail -->
        <div
          class="absolute left-[5%] right-[5%] top-5 h-px pointer-events-none"
          style="background:linear-gradient(90deg, rgba(16,42,80,0) 0%, rgba(16,42,80,0.8) 10%, rgba(16,42,80,0.8) 90%, rgba(16,42,80,0) 100%);"
          aria-hidden="true"
        />

        <div
          v-for="(step, i) in PIPELINE_STEPS"
          :key="step.label"
          class="flex-1 flex flex-col items-center text-center relative z-10 px-2"
        >
          <!-- Step node -->
          <div
            :class="[
              'w-10 h-10 rounded-full flex items-center justify-center text-sm font-mono font-bold mb-3 transition-all duration-200',
              stepNodeClass(i),
            ]"
          >
            <span v-if="i < PIPELINE_STEPS.length - 1">{{ i + 1 }}</span>
            <svg v-else class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>
            </svg>
          </div>
          <p class="text-xs font-mono font-semibold text-white mb-1">{{ step.label }}</p>
          <p class="text-xs leading-relaxed px-1" style="color:rgba(148,163,184,0.55)">{{ step.desc }}</p>
        </div>
      </div>

      <!-- Mobile stacked -->
      <div class="md:hidden space-y-3">
        <div
          v-for="(step, i) in PIPELINE_STEPS"
          :key="step.label"
          class="flex items-start gap-4 p-3 rounded-xl"
          style="background:rgba(10,31,58,0.4); border:1px solid rgba(16,42,80,0.6);"
        >
          <div
            :class="['w-8 h-8 rounded-full flex items-center justify-center text-xs font-mono font-bold shrink-0', stepNodeClass(i)]"
          >
            {{ i + 1 }}
          </div>
          <div>
            <p class="text-sm font-mono font-semibold text-white">{{ step.label }}</p>
            <p class="text-xs mt-0.5" style="color:rgba(148,163,184,0.6)">{{ step.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════════════════════════════════════
         CORE FEATURES
    ══════════════════════════════════════════ -->
    <section class="max-w-5xl mx-auto px-6 pb-24">
      <div class="text-center mb-16">
        <span class="panel-label">Capabilities</span>
        <h2 class="text-3xl md:text-4xl font-bold text-white mt-3">
          Built for serious cardiac simulation
        </h2>
      </div>

      <div class="grid md:grid-cols-2 gap-4">
        <div
          v-for="feat in FEATURES"
          :key="feat.title"
          class="glass-card p-5 flex gap-4 group transition-all duration-200"
          style="cursor:default;"
          :style="{ '--hover-border': feat.borderColor }"
        >
          <!-- Icon -->
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-all duration-200 group-hover:scale-105"
            :style="{ background: feat.iconBg }"
            aria-hidden="true"
          >
            <component :is="feat.icon" class="w-5 h-5" :style="{ color: feat.color }" />
          </div>

          <!-- Text -->
          <div class="space-y-1 min-w-0">
            <h3 class="text-sm font-semibold text-white">{{ feat.title }}</h3>
            <p class="text-xs leading-relaxed" style="color:rgba(148,163,184,0.65)">{{ feat.body }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- ══════════════════════════════════════════
         FINAL CTA
    ══════════════════════════════════════════ -->
    <section class="max-w-3xl mx-auto px-6 pb-24 text-center">
      <div class="glass-card p-10 relative overflow-hidden" style="border-color:rgba(227,27,27,0.15);">
        <!-- ECG grid inside card -->
        <div class="absolute inset-0 ecg-grid-bg opacity-20" aria-hidden="true" />

        <!-- Glow -->
        <div
          class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 rounded-full pointer-events-none"
          style="background:radial-gradient(circle, rgba(227,27,27,0.08) 0%, transparent 70%);"
          aria-hidden="true"
        />

        <div class="relative z-10 space-y-5">
          <h2 class="text-2xl md:text-3xl font-bold text-white">
            Ready to build your cardiac twin?
          </h2>
          <p class="text-sm max-w-md mx-auto leading-relaxed" style="color:rgba(148,163,184,0.65)">
            Upload cardiac reports, enter vitals, and explore a deterministic
            simulation of cardiac function and recovery scenarios with full
            source confidence tracking.
          </p>
          <NuxtLink
            to="/lab"
            class="btn-primary inline-flex items-center gap-2 text-base px-10 py-3 rounded-xl"
            style="box-shadow: 0 0 24px rgba(227,27,27,0.25);"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/>
            </svg>
            Open HeartTwin Lab
          </NuxtLink>
        </div>
      </div>
    </section>

    <!-- ══════════════════════════════════════════
         SAFETY BOUNDARY
    ══════════════════════════════════════════ -->
    <section id="safety" style="border-top:1px solid rgba(16,42,80,0.6);">
      <div class="max-w-2xl mx-auto px-6 py-14 text-center space-y-4">
        <div
          class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-mono"
          style="background:rgba(245,158,11,0.06); border:1px solid rgba(245,158,11,0.18); color:rgba(251,191,36,0.8);"
        >
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
          </svg>
          Safety Boundary
        </div>
        <h3 class="text-xl font-semibold text-white">Educational simulation only.</h3>
        <p class="text-sm leading-relaxed max-w-md mx-auto" style="color:rgba(148,163,184,0.65)">
          Not for diagnosis or treatment decisions. HeartTwin Lab does not provide
          medical advice or clinical recommendations. All outputs are labeled as
          simulated educational estimates.
        </p>
        <div class="flex flex-wrap justify-center gap-3 pt-2 text-xs font-mono" style="color:rgba(148,163,184,0.4)">
          <span>Deterministic physiology engine</span>
          <span aria-hidden="true">·</span>
          <span>Source confidence tracking</span>
          <span aria-hidden="true">·</span>
          <span>Hard safety boundary</span>
          <span aria-hidden="true">·</span>
          <span>Agent trace &amp; audit</span>
        </div>
      </div>
    </section>

  </AppShell>
</template>

<script setup lang="ts">
import { defineComponent, h } from 'vue'
import AppShell from '~/components/layout/AppShell.vue'

// ── Inline SVG icon components ───────────────────────────────
function svgIcon(d: string) {
  return defineComponent({
    setup: () => () => h('svg', { fill: 'none', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '1.5' }, [
      h('path', { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', d }),
    ]),
  })
}

const HeartIcon = svgIcon('M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z')
const GridIcon  = svgIcon('M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3')
const ChartIcon = svgIcon('M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z')
const DocIcon   = svgIcon('M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z')
const ShieldIcon = svgIcon('M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z')
const SearchIcon = svgIcon('M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z')

// ── Data ─────────────────────────────────────────────────────
const METRIC_CHIPS = [
  { key: 'EF',  val: '46.2', unit: '%'     },
  { key: 'CO',  val: '5.28', unit: 'L/min' },
  { key: 'MAP', val: '101',  unit: 'mmHg'  },
  { key: 'HR',  val: '88',   unit: 'bpm'   },
  { key: 'SV',  val: '60',   unit: 'mL'    },
  { key: 'DQ',  val: '92',   unit: '%'     },
]

const PIPELINE_STEPS = [
  { label: 'Upload',           desc: 'PDFs, ECGs, CSVs, or manual vitals' },
  { label: 'Extract',          desc: '8-agent evidence extraction pipeline' },
  { label: 'Validate',         desc: 'Units, plausibility, contradictions' },
  { label: 'Build Twin',       desc: 'Canonical cardiac state assembly' },
  { label: 'Operate',          desc: 'Deterministic hemodynamics + PV loop' },
  { label: 'Sim Recovery',     desc: 'Bounded scenario trajectories' },
]

function stepNodeClass(i: number) {
  if (i === 0) return 'bg-cardiac-red text-white border-2 border-cardiac-red'
  if (i === PIPELINE_STEPS.length - 1) return 'bg-cardiac-blue/15 text-cardiac-electric border-2 border-cardiac-blue/50'
  const progress = i / (PIPELINE_STEPS.length - 1)
  if (progress < 0.4) return 'bg-cardiac-navy-card text-white border-2 border-cardiac-navy-border'
  return 'bg-cardiac-navy-card text-cardiac-muted border-2 border-cardiac-navy-border/60'
}

const FEATURES = [
  {
    icon: DocIcon,
    iconBg: 'rgba(26,111,255,0.10)',
    color: '#7bb8ff',
    borderColor: 'rgba(26,111,255,0.2)',
    title: 'Multimodal cardiac intake',
    body: 'Accepts PDF reports, ECG images, CSV waveforms, and structured vitals. Every extracted value includes source, confidence, and evidence snippet.',
  },
  {
    icon: GridIcon,
    iconBg: 'rgba(227,27,27,0.10)',
    color: '#ff8080',
    borderColor: 'rgba(227,27,27,0.2)',
    title: 'Deterministic physiology engine',
    body: 'SV, EF, CO, MAP, QTc, and PV loop area are computed by deterministic Python formulas. LLM agents never perform math — all numeric output is validated.',
  },
  {
    icon: HeartIcon,
    iconBg: 'rgba(168,85,247,0.10)',
    color: '#c4b5fd',
    borderColor: 'rgba(168,85,247,0.2)',
    title: '3D digital twin visualization',
    body: 'Stylized 3D heart with beat animation, blood flow particles, electrical wave overlay, and damage zone rendering mapped to cardiac state.',
  },
  {
    icon: ChartIcon,
    iconBg: 'rgba(34,197,94,0.10)',
    color: '#4ade80',
    borderColor: 'rgba(34,197,94,0.2)',
    title: 'Recovery scenario engine',
    body: 'Generate 2–4 bounded simulated recovery trajectories with uncertainty bands. All outputs are labeled as bounded model scenarios.',
  },
  {
    icon: SearchIcon,
    iconBg: 'rgba(245,158,11,0.10)',
    color: '#fbbf24',
    borderColor: 'rgba(245,158,11,0.2)',
    title: 'Agent trace and confidence',
    body: 'Every agent decision is inspectable. Source confidence badges on every value. Evaluator scores extraction completeness and hallucination risk.',
  },
  {
    icon: ShieldIcon,
    iconBg: 'rgba(227,27,27,0.08)',
    color: '#fca5a5',
    borderColor: 'rgba(227,27,27,0.15)',
    title: 'Hard safety boundary',
    body: 'Clinical-decision requests are blocked at intake. Every output carries a mandatory educational simulation disclaimer.',
  },
]
</script>

<style scoped>
.text-gradient-red {
  background: linear-gradient(135deg, #fff 0%, var(--ht-red) 42%, #ff9aa9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.panel-label {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: rgba(148, 163, 184, 0.7);
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.panel-label::before {
  display: inline-block;
  width: 1.5rem;
  height: 1px;
  background: linear-gradient(90deg, var(--ht-red), transparent);
  content: "";
}

.glass-card {
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: var(--ht-radius-md);
  background:
    linear-gradient(145deg, rgba(10, 20, 35, 0.9), rgba(4, 10, 20, 0.72)),
    rgba(10, 20, 35, 0.72);
  box-shadow: var(--ht-shadow-panel);
  backdrop-filter: blur(18px);
}

.glass-card:hover {
  border-color: var(--hover-border, rgba(56, 189, 248, 0.28));
  transform: translateY(-2px);
}

.btn-primary,
.btn-secondary {
  min-height: 2.75rem;
  border: 1px solid transparent;
  font-weight: 700;
  letter-spacing: 0;
  transition:
    transform 0.2s ease,
    border-color 0.2s ease,
    background-color 0.2s ease,
    box-shadow 0.2s ease;
}

.btn-primary {
  border-color: rgba(255, 54, 95, 0.42);
  background: linear-gradient(135deg, var(--ht-red), #b91c1c);
  color: #fff;
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: var(--ht-shadow-glow-red);
}

.btn-secondary {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(10, 20, 35, 0.72);
  color: rgba(226, 232, 240, 0.92);
}

.btn-secondary:hover {
  border-color: rgba(56, 189, 248, 0.36);
  background: rgba(56, 189, 248, 0.08);
  color: #fff;
}

@media (prefers-reduced-motion: reduce) {
  .glass-card,
  .btn-primary,
  .btn-secondary {
    transition: none;
  }

  .glass-card:hover,
  .btn-primary:hover {
    transform: none;
  }
}
</style>
