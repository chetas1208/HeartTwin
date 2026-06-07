import type { CardiacTwinState, MeasuredValue } from '@/types/heart'

export function validateMeasuredValue(value: unknown): value is MeasuredValue {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.value === 'number'
    && typeof candidate.unit === 'string'
    && typeof candidate.source === 'string'
    && typeof candidate.confidence === 'number'
    && candidate.confidence >= 0
    && candidate.confidence <= 1
  )
}

export function validateCardiacState(state: unknown): state is CardiacTwinState {
  if (!state || typeof state !== 'object') return false
  const candidate = state as Record<string, unknown>
  return (
    typeof candidate.case_id === 'string'
    && typeof candidate.created_at === 'string'
    && typeof candidate.data_quality_score === 'number'
    && typeof candidate.measurements === 'object'
    && typeof candidate.operating_environment === 'object'
    && typeof candidate.simulation_config === 'object'
  )
}

export function safeParseFloat(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'string' ? Number.parseFloat(value) : value
  return Number.isFinite(parsed) ? parsed : null
}

export function isWithinBounds(value: number, min: number, max: number): boolean {
  return value >= min && value <= max
}

export const VITAL_BOUNDS: Record<string, readonly [number, number]> = {
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

export function validateUserVitals(vitals: Record<string, number | string | null | undefined>): {
  valid: Record<string, number>
  errors: string[]
} {
  const valid: Record<string, number> = {}
  const errors: string[] = []

  for (const [field, rawValue] of Object.entries(vitals)) {
    if (rawValue === null || rawValue === undefined || rawValue === '') continue
    const value = safeParseFloat(rawValue)
    if (value === null) {
      errors.push(`${field}: not a valid number`)
      continue
    }

    const bounds = VITAL_BOUNDS[field]
    if (bounds && !isWithinBounds(value, bounds[0], bounds[1])) {
      errors.push(`${field}: ${value} is outside physiological range [${bounds[0]}, ${bounds[1]}]`)
      continue
    }

    valid[field] = value
  }

  return { valid, errors }
}
