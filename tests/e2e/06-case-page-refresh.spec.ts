import { test, expect } from '@playwright/test'
import { apiBase, baselineVitals } from '../helpers'

/**
 * After running a case, /case/{id} should load and survive a refresh without
 * crashing (it loads the case or shows a clear fallback message).
 */
test.describe('Case page refresh', () => {
  test('case page loads and survives reload', async ({ page, request, baseURL }) => {
    const base = apiBase(baseURL)
    const vitals = baselineVitals()

    const caseId = (await (await request.post(`${base}/cases`, { data: {} })).json()).case_id
    await request.post(`${base}/cases/${caseId}/extract`, { data: { file_ids: [], user_vitals: vitals } })
    await request.post(`${base}/cases/${caseId}/operate`, { data: {} })

    await page.goto(`/case/${caseId}`)
    await expect(page.locator('body')).toBeVisible()

    await page.reload()
    await expect(page.locator('body')).toBeVisible()

    // Either the case id is shown, or a clear fallback message is present.
    const html = (await page.content()).toLowerCase()
    const ok = html.includes(caseId.toLowerCase()) ||
      /not found|unavailable|could not load|no case/.test(html)
    expect(ok).toBeTruthy()
  })
})
