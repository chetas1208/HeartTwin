<template>
  <AppShell :show-nav="true">
    <div class="max-w-3xl mx-auto px-6 py-16 space-y-12">

      <div>
        <span class="section-title">About</span>
        <h1 class="text-4xl font-bold text-white mt-2 leading-tight">HeartTwin Lab</h1>
        <p class="text-lg text-cardiac-muted mt-3 leading-relaxed">
          An agentic cardiac digital twin simulator for education and research. Not a medical device.
        </p>
      </div>

      <MedicalBoundaryBanner />

      <section class="space-y-4">
        <h2 class="text-xl font-semibold text-white">What it is</h2>
        <p class="text-sm text-cardiac-muted leading-relaxed">
          HeartTwin Lab accepts cardiac-related files — PDF reports, ECG images and CSV waveforms,
          echo/MRI-style images, and structured vitals — and builds a simplified, explainable cardiac
          state. It simulates how the heart operates under different conditions and generates bounded
          simulated recovery trajectories through deterministic math and physics tools.
        </p>
        <p class="text-sm text-cardiac-muted leading-relaxed">
          Every extracted value shows its source file, extraction method, and confidence score.
          Every derived value shows the formula used. Every prior value is labeled as a population
          default. Nothing is invented silently.
        </p>
      </section>

      <section class="space-y-3">
        <h2 class="text-xl font-semibold text-white">What it is not</h2>
        <div class="space-y-2">
          <div v-for="item in NOT_LIST" :key="item" class="flex gap-3 items-start">
            <span class="text-cardiac-red font-bold text-sm mt-0.5">x</span>
            <span class="text-sm text-cardiac-muted">{{ item }}</span>
          </div>
        </div>
      </section>

      <section class="space-y-4">
        <h2 class="text-xl font-semibold text-white">The 8-agent pipeline</h2>
        <div class="space-y-3">
          <div v-for="agent in AGENTS" :key="agent.name" class="glass-card p-4 flex gap-4">
            <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold bg-cardiac-red/20 text-cardiac-red shrink-0 mt-0.5">
              {{ agent.stage }}
            </div>
            <div>
              <p class="text-sm font-semibold text-white">{{ agent.name }}</p>
              <p class="text-xs text-cardiac-muted mt-0.5 leading-relaxed">{{ agent.description }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-xl font-semibold text-white">Deterministic formulas</h2>
        <GlassCard class="p-4">
          <p class="text-xs text-cardiac-muted mb-3 font-mono">All numeric outputs come from these explicit, unit-tested Python functions. LLMs never perform math.</p>
          <div class="space-y-1.5 font-mono text-xs">
            <div v-for="f in FORMULAS" :key="f" class="flex gap-2">
              <span class="text-cardiac-electric">></span>
              <span class="text-white">{{ f }}</span>
            </div>
          </div>
        </GlassCard>
      </section>

      <section class="space-y-3">
        <h2 class="text-xl font-semibold text-white">Tech stack</h2>
        <div class="grid grid-cols-2 gap-3">
          <div v-for="t in TECH" :key="t.label" class="glass-card p-3 space-y-0.5">
            <p class="text-xs font-mono text-cardiac-muted">{{ t.category }}</p>
            <p class="text-sm font-semibold text-white">{{ t.label }}</p>
          </div>
        </div>
      </section>

    </div>
  </AppShell>
</template>

<script setup lang="ts">
import AppShell from '~/components/layout/AppShell.vue'

const NOT_LIST = [
  'Not a medical device',
  'Not for diagnosis decisions',
  'Not for treatment decisions',
  'Not for emergency or clinical triage',
  'Not clinically validated',
  'Not a replacement for a qualified clinician',
]

const AGENTS = [
  { stage: 1, name: 'Intake & Safety Agent', description: 'Validates user intent, enforces safety boundaries, rejects clinical-decision requests.' },
  { stage: 2, name: 'Multimodal Extraction Agent', description: 'Extracts structured cardiac values from PDFs, ECG images/CSV, and manual vitals with source, confidence, and evidence.' },
  { stage: 3, name: 'Evidence Validator Agent', description: 'Converts units, flags impossible values, resolves contradictions, preserves conflicting evidence with warnings.' },
  { stage: 4, name: 'Cardiac State Builder Agent', description: 'Maps validated evidence into CardiacTwinState. Uses deterministic formulas for derived values. Marks all priors clearly.' },
  { stage: '5a', name: 'Electrophysiology Agent', description: 'Analyzes ECG data for rhythm and intervals. Uses Pan-Tompkins-style R-peak detection on CSV waveforms.' },
  { stage: '5b', name: 'Hemodynamics Simulation Agent', description: 'Simulates a cardiac cycle via time-varying elastance. Generates PV loop, chamber metrics, and visualization payload.' },
  { stage: 6, name: 'Recovery Orchestration Agent', description: 'Generates 2-4 bounded simulated recovery scenarios with daily trajectories, uncertainty bands, and tradeoff explanations.' },
  { stage: 7, name: 'Evaluator & Critic Agent', description: 'Scores extraction completeness, physiological plausibility, hallucination risk, and safety compliance. Blocks unsafe outputs.' },
]

const FORMULAS = [
  'SV  = EDV - ESV',
  'EF  = (SV / EDV) x 100',
  'CO  = (HR x SV) / 1000',
  'MAP = DBP + (SBP - DBP) / 3',
  'RR  = 60000 / HR',
  'QTc = QT / sqrt(RR in seconds)  [Bazett]',
  'BSA = sqrt(H x W / 3600)         [Mosteller]',
  'PV loop area via shoelace formula',
  'Recovery: exponential decay + bounded daily deltas',
]

const TECH = [
  { category: 'Frontend', label: 'Nuxt 4 + Vue 3' },
  { category: 'State management', label: 'Pinia' },
  { category: '3D visualization', label: 'TresJS + Three.js' },
  { category: 'Charts', label: 'Plotly.js' },
  { category: 'Validation', label: 'Zod + Pydantic' },
  { category: 'API', label: 'Python FastAPI' },
  { category: 'Storage', label: 'Vercel Blob + Upstash Redis' },
  { category: 'Deploy', label: 'Vercel (serverless, root repo)' },
]
</script>

<style scoped>
.section-title {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: rgba(148, 163, 184, 0.72);
  font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.section-title::after {
  display: inline-block;
  width: 2rem;
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
</style>
