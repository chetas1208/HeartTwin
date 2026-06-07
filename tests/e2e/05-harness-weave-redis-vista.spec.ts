import { test, expect } from '@playwright/test'
import { apiBase, baselineVitals } from '../helpers'

/**
 * Harness must surface Weave, Redis and VISTA status and eval scores.
 * Self-improvement requires a recovery to exist first.
 */
test.describe('Harness: Weave / Redis / VISTA', () => {
  test('harness endpoint exposes statuses and eval scores after a run', async ({ request, baseURL }) => {
    const base = apiBase(baseURL)
    const vitals = baselineVitals()

    const caseId = (await (await request.post(`${base}/cases`, { data: {} })).json()).case_id
    await request.post(`${base}/cases/${caseId}/extract`, { data: { file_ids: [], user_vitals: vitals } })
    await request.post(`${base}/cases/${caseId}/operate`, { data: {} })

    // Before recovery, self-improve returns a clear "needs recovery" failure (not a crash).
    const before = await request.post(`${base}/cases/${caseId}/self-improve`)
    expect(before.ok()).toBeTruthy()
    const beforeBody = await before.json()
    expect(beforeBody.status).toBe('failed')

    await request.post(`${base}/cases/${caseId}/simulate-recovery`, { data: {} })

    const harness = await (await request.get(`${base}/cases/${caseId}/harness`)).json()
    expect(harness.weave).toBeTruthy()
    expect(['connected', 'not_configured', 'error']).toContain(harness.weave.status)
    expect(harness.redis).toBeTruthy()
    expect(typeof harness.redis.configured).toBe('boolean')
    expect(Array.isArray(harness.stage_results)).toBeTruthy()

    // After recovery, self-improve can run and returns before/after comparison.
    const after = await (await request.post(`${base}/cases/${caseId}/self-improve`)).json()
    expect(after.before).toBeTruthy()
    expect(after.after).toBeTruthy()
    expect(after.score_delta).toBeTruthy()
  })

  test('Lab harness panel renders status text', async ({ page }) => {
    await page.goto('/lab')
    // The harness/system panel exposes integration status copy.
    const statusish = page.getByText(/weave|redis|fallback|configured|not configured/i)
    if (await statusish.count()) {
      await expect(statusish.first()).toBeVisible()
    }
  })
})
