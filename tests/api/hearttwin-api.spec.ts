import { test, expect } from '@playwright/test'
import { apiBase, baselineVitals, assertNoSecretLeak, UNSAFE_PHRASES } from '../helpers'

/**
 * Pure API tests via Playwright's request context (no browser needed beyond the
 * package). Catches server/API bugs before UI noise. Runs the full pipeline.
 */
test.describe('HeartTwin API', () => {
  let base: string
  let caseId: string

  test.beforeAll(({ }, testInfo) => {
    base = apiBase(testInfo.project.use.baseURL as string | undefined)
  })

  test('health', async ({ request }) => {
    const res = await request.get(`${base}/health`)
    expect(res.ok()).toBeTruthy()
    expect((await res.json()).status).toBe('ok')
  })

  test('config (safe, no secrets)', async ({ request }) => {
    const res = await request.get(`${base}/config`)
    expect(res.ok()).toBeTruthy()
    const text = await res.text()
    expect(assertNoSecretLeak(text)).toEqual([])
  })

  test('system-check', async ({ request }) => {
    const res = await request.get(`${base}/system-check`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.integrations).toBeTruthy()
    expect(body.metrics).toBeTruthy()
  })

  test('create case', async ({ request }) => {
    const res = await request.post(`${base}/cases`, { data: {} })
    expect(res.ok()).toBeTruthy()
    caseId = (await res.json()).case_id
    expect(caseId).toBeTruthy()
  })

  test('extract with baseline fixture', async ({ request }) => {
    const res = await request.post(`${base}/cases/${caseId}/extract`, {
      data: { file_ids: [], user_vitals: baselineVitals() },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.validated_field_count).toBeGreaterThanOrEqual(5)
    for (const f of ['heart_rate_bpm', 'systolic_bp_mmhg', 'diastolic_bp_mmhg', 'edv_ml', 'esv_ml']) {
      expect(body.validated_fields[f]).toBeDefined()
    }
  })

  test('operate', async ({ request }) => {
    const res = await request.post(`${base}/cases/${caseId}/operate`, { data: {} })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    const s = body.visualization.summary
    expect(s.stroke_volume_ml).toBeCloseTo(70, 0)
    expect(s.ef_pct).toBeGreaterThan(57)
    expect(body.visualization.pv_loop.length ?? Object.keys(body.visualization.pv_loop).length).toBeGreaterThan(0)
    expect(body.visualization['3d_heart']).toBeTruthy()
  })

  test('simulate recovery', async ({ request }) => {
    const res = await request.post(`${base}/cases/${caseId}/simulate-recovery`, { data: {} })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.scenarios.length).toBeGreaterThanOrEqual(2)
    expect(body.scenarios.length).toBeLessThanOrEqual(4)
    const blob = JSON.stringify(body).toLowerCase()
    for (const p of UNSAFE_PHRASES) expect(blob.includes(p)).toBeFalsy()
  })

  test('self-improve', async ({ request }) => {
    const res = await request.post(`${base}/cases/${caseId}/self-improve`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.before).toBeTruthy()
    expect(body.after).toBeTruthy()
  })

  test('harness', async ({ request }) => {
    const res = await request.get(`${base}/cases/${caseId}/harness`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.weave).toBeTruthy()
    expect(body.redis).toBeTruthy()
    expect(Array.isArray(body.stage_results)).toBeTruthy()
  })

  test('trace has 8 agent stages', async ({ request }) => {
    const res = await request.get(`${base}/cases/${caseId}/trace`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.weave.traced_stages_count).toBeGreaterThanOrEqual(8)
  })
})
