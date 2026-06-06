import type { CardiacTwinState, MeasuredValue } from '~/types/heart'

export function validateMeasuredValue(mv: unknown): mv is MeasuredValue {
  if (!mv || typeof mv !== 'object') return false
  const obj = mv as Record<string, unknown>
  return (
    typeof obj.value === 'number'
    && typeof obj.unit === 'string'
    && typeof obj.source === 'string'
    && typeof obj.confidence === 'number'
    && obj.confidence >= 0
    && obj.confidence <= 1
  )
}

export function validateCardiacState(state: unknown): state is CardiacTwinState {
  if (!state || typeof state !== 'object') return false
  const s = state as Record<string, unknown>
  return (
    typeof s.case_id === 'string'
    && typeof s.data_quality_score === 'number'
    && typeof s.measurements === 'object'
  )
}

export function safeParseFloat(val: string | number | null | undefined): number | null {
  if (val === null || val === undefined || val === '') return null
  const n = typeof val === 'string' ? Number.parseFloat(val) : val
  return Number.isFinite(n) ? n : null
}

export function isWithinBounds(val: number, min: number, max: number): boolean {
  return val >= min && val <= max
}

const VITAL_BOUNDS: Record<string, [number, number]> = {
  heart_rate_bpm: [20, 280],
  systolic_bp_mmhg: [50, 260],
  diastolic_bp_mmhg: [20, 160],
  ejection_fraction_pct: [5, 90],
  edv_ml: [30, 400],
  esv_ml: [5, 350],
  cardiac_output_l_min: [0.5, 40],
  oxygen_saturation_pct: [50, 100],
  age_years: [0, 130],
  height_cm: [30, 280],
  weight_kg: [1, 500],
}

export function validateUserVitals(vitals: Record<string, number | string | null>): {
  valid: Record<string, number>
  errors: string[]
} {
  const valid: Record<string, number> = {}
  const errors: string[] = []

  for (const [field, rawVal] of Object.entries(vitals)) {
    if (rawVal === null || rawVal === '' || rawVal === undefined) continue
    const n = safeParseFloat(rawVal as string | number)
    if (n === null) {
      errors.push(`${field}: not a valid number`)
      continue
    }
    const bounds = VITAL_BOUNDS[field]
    if (bounds && !isWithinBounds(n, bounds[0], bounds[1])) {
      errors.push(`${field}: ${n} is outside physiological range [${bounds[0]}, ${bounds[1]}]`)
      continue
    }
    valid[field] = n
  }

  return { valid, errors }
}
