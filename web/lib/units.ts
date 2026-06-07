import type { MeasuredValue, ValueSource } from '@/types/heart'

export function formatMeasuredValue(value: MeasuredValue | null | undefined, decimals = 1): string {
  if (!value) return '-'
  const numericValue = Number.isFinite(value.value) ? value.value.toFixed(decimals) : String(value.value)
  return `${numericValue} ${value.unit}`.trim()
}

export function getMeasuredValue(value: MeasuredValue | null | undefined): number | null {
  if (!value || typeof value.value !== 'number') return null
  return value.value
}

export function confidenceLabel(confidence: number): string {
  if (confidence >= 0.85) return 'high'
  if (confidence >= 0.65) return 'moderate'
  if (confidence >= 0.4) return 'low'
  return 'very low'
}

export function confidenceColor(confidence: number): string {
  if (confidence >= 0.85) return 'text-green-400'
  if (confidence >= 0.65) return 'text-yellow-400'
  if (confidence >= 0.4) return 'text-orange-400'
  return 'text-red-400'
}

export function sourceLabel(source: ValueSource): string {
  const labels: Record<ValueSource, string> = {
    file_extraction: 'Extracted from file',
    user_input: 'User provided',
    default_model_prior: 'Population prior',
    derived: 'Deterministic formula',
  }
  return labels[source] ?? source
}

export function sourceBadgeClass(source: ValueSource): string {
  const classes: Record<ValueSource, string> = {
    file_extraction: 'badge-extracted',
    user_input: 'badge-user',
    default_model_prior: 'badge-default',
    derived: 'badge-extracted',
  }
  return classes[source] ?? ''
}

export function sourceMethodLabel(method: string | null | undefined): string {
  const labels: Record<string, string> = {
    manual_input: 'Manual input',
    pdf_text: 'PDF text',
    csv_parse: 'CSV parse',
    csv_waveform: 'CSV waveform',
    deterministic_formula: 'Deterministic formula',
    prior: 'Population prior',
    vision_api_gpt4o: 'Vision API',
    waveform_analysis: 'Waveform analysis',
    bazett_formula: 'Bazett formula',
    qrs_threshold_rule: 'QRS threshold',
    user_input: 'User input',
  }
  if (!method) return ''
  if (method.startsWith('regex:')) return `PDF regex (${method.slice(6)})`
  return labels[method] ?? method
}

export function dataQualityLabel(score: number): string {
  if (score >= 0.75) return 'Good'
  if (score >= 0.5) return 'Fair'
  if (score >= 0.25) return 'Poor'
  return 'Minimal'
}

export function dataQualityColor(score: number): string {
  if (score >= 0.75) return 'text-green-400'
  if (score >= 0.5) return 'text-yellow-400'
  if (score >= 0.25) return 'text-orange-400'
  return 'text-red-400'
}
