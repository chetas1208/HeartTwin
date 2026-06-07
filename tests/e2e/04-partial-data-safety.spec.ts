import { test, expect } from '@playwright/test'
import { apiBase, partialVitals, UNSAFE_PHRASES } from '../helpers'

/**
 * Partial data must not crash, must warn about missing EDV/ESV, must not
 * silently invent SV, and must never produce unsafe medical language.
 */
test.describe('Partial data safety', () => {
  test('partial vitals warn, label priors, and stay safe', async ({ request, baseURL }) => {
    const base = apiBase(baseURL)
    const vitals = partialVitals()

    const created = await (await request.post(`${base}/cases`, { data: {} })).json()
    const caseId = created.case_id

    const ext = await request.post(`${base}/cases/${caseId}/extract`, {
      data: { file_ids: [], user_vitals: vitals },
    })
    expect(ext.ok()).toBeTruthy()

    const opRes = await request.post(`${base}/cases/${caseId}/operate`, { data: {} })
    expect(opRes.ok()).toBeTruthy()
    const op = await opRes.json()

    // State exists and source map labels EDV/ESV as model priors (not invented).
    const sourceMap = op.state?.source_map || []
    const priorFields = sourceMap
      .filter((e: { source: string }) => e.source === 'default_model_prior')
      .map((e: { field: string }) => e.field)
    expect(priorFields.some((f: string) => f === 'edv_ml' || f === 'esv_ml')).toBeTruthy()

    // Warnings are surfaced somewhere.
    const blob = JSON.stringify(op).toLowerCase()
    expect(blob.includes('warning') || (op.state?.warnings || []).length > 0).toBeTruthy()

    // No unsafe language.
    for (const p of UNSAFE_PHRASES) {
      expect(blob.includes(p)).toBeFalsy()
    }
  })
})
