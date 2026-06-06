<template>
  <div class="manual-vitals-card glass-card p-5 space-y-5">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-mono font-semibold text-white uppercase tracking-widest">
        Manual Vitals Input
      </h3>
      <span class="sim-label">source: user_input</span>
    </div>

    <p class="text-xs text-cardiac-muted leading-relaxed">
      Enter known cardiac values. All fields are optional. Entered values are marked
      <span class="text-green-400 font-mono">user_input</span> with full confidence.
      Missing fields use population priors and are clearly labeled.
    </p>

    <form class="space-y-5" @submit.prevent="handleSubmit">
      <!-- Hemodynamic measurements -->
      <fieldset class="space-y-3">
        <legend class="section-title">Hemodynamic Measurements</legend>
        <div class="grid grid-cols-2 gap-3">
          <VitalField
            v-model="form.heart_rate_bpm"
            label="Heart Rate"
            unit="bpm"
            :min="20"
            :max="280"
            placeholder="e.g. 72"
            :error="fieldError('heart_rate_bpm')"
          />
          <VitalField
            v-model="form.oxygen_saturation_pct"
            label="O₂ Saturation"
            unit="%"
            :min="50"
            :max="100"
            placeholder="e.g. 98"
            :error="fieldError('oxygen_saturation_pct')"
          />
          <VitalField
            v-model="form.systolic_bp_mmhg"
            label="Systolic BP"
            unit="mmHg"
            :min="50"
            :max="260"
            placeholder="e.g. 120"
            :error="fieldError('systolic_bp_mmhg')"
          />
          <VitalField
            v-model="form.diastolic_bp_mmhg"
            label="Diastolic BP"
            unit="mmHg"
            :min="20"
            :max="160"
            placeholder="e.g. 80"
            :error="fieldError('diastolic_bp_mmhg')"
          />
          <VitalField
            v-model="form.edv_ml"
            label="EDV"
            unit="mL"
            :min="30"
            :max="400"
            placeholder="e.g. 130"
            :error="fieldError('edv_ml')"
          />
          <VitalField
            v-model="form.esv_ml"
            label="ESV"
            unit="mL"
            :min="5"
            :max="350"
            placeholder="e.g. 50"
            :error="fieldError('esv_ml')"
          />
          <VitalField
            v-model="form.ejection_fraction_pct"
            label="Ejection Fraction"
            unit="%"
            :min="5"
            :max="90"
            placeholder="e.g. 60"
            :error="fieldError('ejection_fraction_pct')"
          />
        </div>
      </fieldset>

      <!-- Biomarkers -->
      <fieldset class="space-y-3">
        <legend class="section-title">Biomarkers</legend>
        <div class="grid grid-cols-2 gap-3">
          <VitalField
            v-model="form.troponin_ng_l"
            label="Troponin"
            unit="ng/L"
            :min="0"
            placeholder="e.g. 14"
            :error="fieldError('troponin_ng_l')"
          />
          <VitalField
            v-model="form.bnp_pg_ml"
            label="BNP"
            unit="pg/mL"
            :min="0"
            placeholder="e.g. 100"
            :error="fieldError('bnp_pg_ml')"
          />
        </div>
      </fieldset>

      <!-- Patient context -->
      <fieldset class="space-y-3">
        <legend class="section-title">Patient Context <span class="text-cardiac-muted normal-case font-normal">(optional)</span></legend>
        <div class="grid grid-cols-2 gap-3">
          <VitalField
            v-model="form.age_years"
            label="Age"
            unit="years"
            :min="0"
            :max="130"
            placeholder="e.g. 55"
            :error="fieldError('age_years')"
          />
          <div class="space-y-1">
            <label class="metric-label">Sex</label>
            <select
              v-model="form.sex"
              class="w-full bg-cardiac-navy border border-cardiac-navy-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cardiac-red/50"
            >
              <option value="">Not specified</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
          </div>
          <VitalField
            v-model="form.height_cm"
            label="Height"
            unit="cm"
            :min="50"
            :max="250"
            placeholder="e.g. 175"
            :error="fieldError('height_cm')"
          />
          <VitalField
            v-model="form.weight_kg"
            label="Weight"
            unit="kg"
            :min="1"
            :max="500"
            placeholder="e.g. 75"
            :error="fieldError('weight_kg')"
          />
        </div>

        <div class="space-y-1">
          <label class="metric-label">Clinical Notes</label>
          <textarea
            v-model="form.notes"
            rows="2"
            maxlength="500"
            placeholder="Optional notes (not used for simulation)"
            class="w-full bg-cardiac-navy border border-cardiac-navy-border rounded-lg px-3 py-2 text-sm text-white placeholder-cardiac-muted/50 focus:outline-none focus:border-cardiac-red/50 resize-none"
          />
          <p class="text-xs text-cardiac-muted">{{ (form.notes ?? '').length }}/500</p>
        </div>
      </fieldset>

      <!-- Validation errors -->
      <div v-if="formErrors.length" class="p-3 rounded-lg bg-cardiac-red/10 border border-cardiac-red/30 space-y-1">
        <p v-for="err in formErrors" :key="err" class="text-xs text-cardiac-red-glow font-mono">
          ⚠ {{ err }}
        </p>
      </div>

      <!-- Actions -->
      <div class="flex gap-3">
        <button type="submit" class="btn-primary flex-1" :disabled="!hasAnyValue">
          Apply Vitals
        </button>
        <button type="button" class="btn-secondary" @click="clearForm">
          Clear
        </button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, ref } from 'vue'
import { ManualVitalsSchema, type ManualVitals } from '~/utils/schemas'

const emit = defineEmits<{
  submit: [vitals: ManualVitals]
}>()

const form = reactive<ManualVitals>({
  heart_rate_bpm: undefined,
  systolic_bp_mmhg: undefined,
  diastolic_bp_mmhg: undefined,
  edv_ml: undefined,
  esv_ml: undefined,
  ejection_fraction_pct: undefined,
  troponin_ng_l: undefined,
  bnp_pg_ml: undefined,
  oxygen_saturation_pct: undefined,
  age_years: undefined,
  sex: undefined,
  height_cm: undefined,
  weight_kg: undefined,
  notes: undefined,
})

const fieldErrorMap = ref<Record<string, string>>({})
const formErrors = ref<string[]>([])

const hasAnyValue = computed(() =>
  Object.entries(form).some(([k, v]) => k !== 'notes' && k !== 'sex' && v != null),
)

function fieldError(field: string): string {
  return fieldErrorMap.value[field] ?? ''
}

function clearForm() {
  Object.keys(form).forEach((k) => {
    ;(form as Record<string, unknown>)[k] = undefined
  })
  fieldErrorMap.value = {}
  formErrors.value = []
}

function handleSubmit() {
  fieldErrorMap.value = {}
  formErrors.value = []

  const cleaned = Object.fromEntries(
    Object.entries(form).filter(([, v]) => v != null),
  )

  const result = ManualVitalsSchema.safeParse(cleaned)

  if (!result.success) {
    for (const issue of result.error.issues) {
      const path = issue.path[0] as string | undefined
      if (path) {
        fieldErrorMap.value[path] = issue.message
      } else {
        formErrors.value.push(issue.message)
      }
    }
    return
  }

  emit('submit', result.data)
}
</script>

<style scoped>
.manual-vitals-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.88), rgba(7, 17, 31, 0.72));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-lg);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.25);
}

.sim-label {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem 0.5rem;
  color: var(--ht-cyan);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.68rem;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 999px;
}

.section-title,
.metric-label {
  color: rgba(142, 160, 184, 0.76);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.10em;
  text-transform: uppercase;
}

select,
textarea {
  background: rgba(3, 7, 17, 0.82);
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

select:focus,
textarea:focus {
  border-color: rgba(56, 189, 248, 0.55);
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
}

.btn-primary,
.btn-secondary {
  min-height: 2.35rem;
  border-radius: var(--ht-radius-sm);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.8rem;
  font-weight: 700;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.btn-primary {
  color: #fff;
  background: linear-gradient(135deg, var(--ht-red), #cf123f);
  border: 1px solid rgba(255, 255, 255, 0.10);
}

.btn-primary:not(:disabled):hover {
  box-shadow: var(--ht-shadow-glow-red);
  transform: translateY(-1px);
}

.btn-primary:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.btn-secondary {
  color: var(--ht-muted);
  background: rgba(10, 20, 35, 0.76);
  border: 1px solid var(--ht-border);
}

.btn-secondary:hover {
  color: var(--ht-text);
  border-color: rgba(56, 189, 248, 0.35);
}

@media (max-width: 520px) {
  fieldset .grid {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .btn-primary,
  .btn-secondary,
  select,
  textarea {
    transition: none;
  }

  .btn-primary:not(:disabled):hover {
    transform: none;
  }
}
</style>
