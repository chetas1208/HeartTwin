import { test, expect } from '@playwright/test'
import { apiBase, assertNoSecretLeak } from '../helpers'

/**
 * Production smoke test. Runnable against a deployed URL via E2E_BASE_URL, or
 * the local dev server by default. Verifies the spine: root loads, health,
 * config safety, lab loads, system-check works, no secret leakage.
 */
test.describe('Production smoke', () => {
  test('root loads', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(/HeartTwin/i)
  })

  test('health route works', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/health`)
    expect(res.ok()).toBeTruthy()
    expect((await res.json()).status).toBe('ok')
  })

  test('config is safe', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/config`)
    expect(res.ok()).toBeTruthy()
    const text = await res.text()
    expect(assertNoSecretLeak(text)).toEqual([])
  })

  test('lab loads', async ({ page }) => {
    await page.goto('/lab')
    await expect(page).toHaveURL(/\/lab/)
  })

  test('system-check works and leaks no secrets', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/system-check`)
    expect(res.ok()).toBeTruthy()
    const text = await res.text()
    expect(assertNoSecretLeak(text)).toEqual([])
    const body = JSON.parse(text)
    expect(['ok', 'warning', 'failed']).toContain(body.status)
  })
})
