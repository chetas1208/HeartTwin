/**
 * Shared helpers for HeartTwin Playwright specs.
 *
 * Not collected as a test (filename lacks `.spec`).
 */
import fs from 'node:fs'
import path from 'node:path'

export const SAFETY_PHRASE =
  'Educational cardiac simulation only. Not for diagnosis or treatment decisions.'

export const UNSAFE_PHRASES = [
  'you should take',
  'treatment plan',
  'prescribe',
  'dosage',
  'recommend medication',
  'patient improved medically',
  'recovery guaranteed',
]

export const SECRET_PATTERNS = [/sk-[A-Za-z0-9]{16,}/, /AKIA[0-9A-Z]{16}/]

export function apiBase(baseURL?: string): string {
  if (process.env.E2E_API_BASE) return process.env.E2E_API_BASE.replace(/\/$/, '')
  const root = (baseURL || process.env.E2E_BASE_URL || 'http://localhost:3001').replace(/\/$/, '')
  return `${root}/api/v1`
}

export function loadFixture(name: string): Record<string, unknown> {
  const p = path.resolve(__dirname, '..', 'fixtures', 'hearttwin', name)
  return JSON.parse(fs.readFileSync(p, 'utf-8'))
}

export function baselineVitals(): Record<string, number> {
  const data = loadFixture('manual_baseline.json') as { user_vitals: Record<string, number> }
  return data.user_vitals
}

export function partialVitals(): Record<string, number> {
  const data = loadFixture('manual_partial_data.json') as { user_vitals: Record<string, number> }
  return data.user_vitals
}

/** Assert a JSON blob contains no obvious secret values. */
export function assertNoSecretLeak(text: string): string[] {
  const leaks: string[] = []
  for (const re of SECRET_PATTERNS) {
    if (re.test(text)) leaks.push(re.source)
  }
  return leaks
}
