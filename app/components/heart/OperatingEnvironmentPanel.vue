<template>
  <div class="glass-card p-4 space-y-4">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h3 class="panel-label m-0">Operating Environment</h3>
        <p class="text-[10px] font-mono mt-0.5" style="color:rgba(148,163,184,0.4)">Simulation input parameters</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="text-[10px] font-mono px-2 py-1 rounded transition-colors"
          style="color:rgba(148,163,184,0.5); background:rgba(16,42,80,0.4); border:1px solid rgba(16,42,80,0.7);"
          title="Reset to defaults"
          @click="resetDefaults"
        >
          Reset
        </button>
      </div>
    </div>

    <!-- Mode selector -->
    <div>
      <label class="label-mono mb-1.5 block" id="env-mode-label">Physiological Mode</label>
      <div class="grid grid-cols-2 gap-1" role="radiogroup" aria-labelledby="env-mode-label">
        <button
          v-for="m in MODES"
          :key="m.value"
          role="radio"
          :aria-checked="env.mode === m.value"
          :class="[
            'px-2.5 py-2 rounded-lg text-[11px] font-mono transition-all duration-150 text-left',
            env.mode === m.value
              ? 'text-white'
              : 'text-cardiac-muted hover:text-white/70',
          ]"
          :style="env.mode === m.value
            ? 'background:rgba(227,27,27,0.18); border:1px solid rgba(227,27,27,0.4);'
            : 'background:rgba(16,42,80,0.4); border:1px solid rgba(16,42,80,0.7);'"
          @click="env.mode = m.value"
        >
          <span class="block font-semibold">{{ m.label }}</span>
          <span class="text-[9px] opacity-60">{{ m.desc }}</span>
        </button>
      </div>
    </div>

    <!-- Sliders -->
    <div class="space-y-3.5">
      <EnvSlider
        v-model="env.activity_level_mets"
        label="Activity Level"
        unit="METs"
        :min="1"
        :max="12"
        :step="0.5"
        tooltip="Metabolic equivalents. 1 = rest, 3–6 = moderate, 6+ = vigorous exercise."
      />
      <EnvSlider
        v-model="env.hydration_index"
        label="Hydration"
        unit="idx"
        :min="0.5"
        :max="1.5"
        :step="0.05"
        tooltip="1.0 = euhydrated. <0.8 = dehydrated. >1.2 = hyperhydrated."
      />
      <EnvSlider
        v-model="env.stress_catecholamine_index"
        label="Stress / Catecholamines"
        unit="idx"
        :min="0.5"
        :max="3.0"
        :step="0.1"
        tooltip="Sympathetic tone index. 1.0 = baseline. Affects HR and contractility."
      />
      <EnvSlider
        v-model="env.oxygen_fraction"
        label="O₂ Fraction (FiO₂)"
        unit=""
        :min="0.10"
        :max="1.00"
        :step="0.01"
        tooltip="Inspired oxygen fraction. 0.21 = room air. 1.0 = pure O₂."
        :format="(v) => v.toFixed(2)"
      />
      <EnvSlider
        v-model="env.altitude_m"
        label="Altitude"
        unit="m"
        :min="0"
        :max="5000"
        :step="100"
        tooltip="Altitude above sea level. Affects effective O₂ partial pressure."
        :format="(v) => String(Math.round(v))"
      />
      <EnvSlider
        v-model="env.sleep_recovery_index"
        label="Sleep / Recovery"
        unit="idx"
        :min="0"
        :max="1.5"
        :step="0.05"
        tooltip="0 = severely sleep deprived. 1.0 = well rested. Affects recovery capacity."
      />
    </div>

    <!-- Uncertainty policy -->
    <div>
      <label class="label-mono mb-1 block" for="uncertainty-policy">Data Uncertainty Policy</label>
      <select
        id="uncertainty-policy"
        v-model="env.data_uncertainty_policy"
        class="w-full rounded px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none transition-colors"
        style="background:rgba(3,13,26,0.8); border:1px solid rgba(16,42,80,0.9);"
      >
        <option value="conservative">Conservative — prefer lower-bound estimates</option>
        <option value="moderate">Moderate — use model median</option>
        <option value="optimistic">Optimistic — prefer upper-bound estimates</option>
      </select>
      <p class="text-[10px] font-mono mt-1" style="color:rgba(148,163,184,0.35)">
        Affects how missing values are filled from priors.
      </p>
    </div>

    <!-- Run button -->
    <button
      class="btn-primary w-full text-sm py-2.5"
      :disabled="disabled"
      :title="disabled ? 'Create a case and extract evidence before running' : 'Run hemodynamics simulation with these parameters'"
      @click="$emit('run', { ...env })"
    >
      <span class="flex items-center justify-center gap-2">
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z"/>
        </svg>
        Run Simulation
      </span>
    </button>
    <p v-if="disabled" class="text-[10px] font-mono text-center" style="color:rgba(148,163,184,0.35)">
      Disabled: extract evidence or enter vitals first
    </p>
  </div>
</template>

<script setup lang="ts">
import { reactive, defineComponent, h } from 'vue'
import type { OperatingEnvironment } from '~/types/heart'

const MODES = [
  { value: 'rest',          label: 'Rest',          desc: 'Basal state' },
  { value: 'mild_activity', label: 'Mild Activity',  desc: '~3–4 METs' },
  { value: 'stress',        label: 'Stress',         desc: 'Elevated catecholamines' },
  { value: 'recovery',      label: 'Recovery',       desc: 'Post-exercise / post-op' },
] as const

const DEFAULTS: OperatingEnvironment = {
  mode: 'rest',
  simulation_duration_seconds: 1.0,
  time_step_ms: 10,
  activity_level_mets: 1.0,
  hydration_index: 1.0,
  stress_catecholamine_index: 1.0,
  sleep_recovery_index: 1.0,
  oxygen_fraction: 0.21,
  ambient_temperature_c: 22.0,
  altitude_m: 0,
  data_uncertainty_policy: 'moderate',
  missing_value_policy: 'prior',
}

const props = withDefaults(defineProps<{
  initial?: Partial<OperatingEnvironment>
  disabled?: boolean
}>(), { disabled: false })

defineEmits<{ run: [env: OperatingEnvironment] }>()

const env = reactive<OperatingEnvironment>({ ...DEFAULTS, ...props.initial })

function resetDefaults() {
  Object.assign(env, DEFAULTS)
}

const EnvSlider = defineComponent({
  props: {
    modelValue: { type: Number, required: true },
    label: { type: String, required: true },
    unit: { type: String, default: '' },
    min: { type: Number, default: 0 },
    max: { type: Number, default: 1 },
    step: { type: Number, default: 0.1 },
    tooltip: { type: String, default: '' },
    format: { type: Function as unknown as () => ((n: number) => string) | null, default: null },
  },
  emits: ['update:modelValue'],
  setup(sp, { emit: se }) {
    const fmt = (v: number) => {
      if (sp.format) return (sp.format as (n: number) => string)(v)
      const decimals = sp.step < 0.1 ? 2 : sp.step < 1 ? 2 : 1
      return v.toFixed(decimals)
    }
    const pct = (v: number) => ((v - sp.min) / (sp.max - sp.min)) * 100

    return () =>
      h('div', { class: 'space-y-1.5', title: sp.tooltip || undefined }, [
        h('div', { class: 'flex items-center justify-between' }, [
          h('div', { class: 'flex items-center gap-1' }, [
            h('label', { class: 'text-xs font-mono', style: 'color:rgba(148,163,184,0.65)' }, sp.label),
            sp.tooltip
              ? h('span', {
                  class: 'w-3 h-3 rounded-full flex items-center justify-center text-[8px] cursor-help',
                  style: 'background:rgba(16,42,80,0.6); color:rgba(148,163,184,0.5); border:1px solid rgba(16,42,80,0.9);',
                  title: sp.tooltip,
                }, '?')
              : null,
          ]),
          h('span', {
            class: 'text-xs font-mono tabular-nums font-semibold text-white',
          }, `${fmt(sp.modelValue)}${sp.unit ? ` ${sp.unit}` : ''}`),
        ]),
        h('div', { class: 'relative' }, [
          h('div', {
            class: 'absolute top-1/2 -translate-y-1/2 left-0 h-0.5 rounded-full pointer-events-none',
            style: `width:${pct(sp.modelValue)}%; background:rgba(227,27,27,0.7);`,
            'aria-hidden': 'true',
          }),
          h('input', {
            type: 'range',
            min: sp.min,
            max: sp.max,
            step: sp.step,
            value: sp.modelValue,
            class: 'sci-range',
            'aria-label': sp.label,
            onInput: (e: Event) =>
              se('update:modelValue', Number.parseFloat((e.target as HTMLInputElement).value)),
          }),
        ]),
      ])
  },
})
</script>

<style scoped>
.glass-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.88), rgba(7, 17, 31, 0.72));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-lg);
  box-shadow: 0 18px 58px rgba(0, 0, 0, 0.28);
}

.panel-label,
.label-mono {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.11em;
  text-transform: uppercase;
}

button[role="radio"] {
  min-height: 3.25rem;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

button[role="radio"][aria-checked="true"] {
  box-shadow: var(--ht-shadow-glow-red);
}

select {
  background: rgba(3, 7, 17, 0.82) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
}

select:focus {
  border-color: rgba(56, 189, 248, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
}

.btn-primary {
  color: #fff;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-weight: 700;
  background: linear-gradient(135deg, var(--ht-red), #cf123f);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: var(--ht-radius-sm);
  transition: box-shadow 160ms ease, transform 160ms ease;
}

.btn-primary:not(:disabled):hover {
  box-shadow: var(--ht-shadow-glow-red);
  transform: translateY(-1px);
}

.btn-primary:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

:deep(.sci-range) {
  width: 100%;
  height: 0.25rem;
  appearance: none;
  cursor: pointer;
  background: rgba(30, 41, 59, 0.88);
  border-radius: 999px;
  outline: none;
}

:deep(.sci-range::-webkit-slider-thumb) {
  width: 0.9rem;
  height: 0.9rem;
  appearance: none;
  background: var(--ht-red);
  border: 2px solid rgba(255, 255, 255, 0.18);
  border-radius: 50%;
  box-shadow: 0 0 10px rgba(255, 54, 95, 0.52);
}

:deep(.sci-range::-moz-range-thumb) {
  width: 0.9rem;
  height: 0.9rem;
  background: var(--ht-red);
  border: 2px solid rgba(255, 255, 255, 0.18);
  border-radius: 50%;
  box-shadow: 0 0 10px rgba(255, 54, 95, 0.52);
}

@media (prefers-reduced-motion: reduce) {
  button,
  select,
  .btn-primary {
    transition: none;
  }

  .btn-primary:not(:disabled):hover {
    transform: none;
  }
}
</style>
