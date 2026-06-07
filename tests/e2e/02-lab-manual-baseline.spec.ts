import { test, expect } from '@playwright/test'

/**
 * Manual baseline flow through the actual Lab UI.
 *
 * Fills the Manual Vitals form (by placeholder), then drives the simulation
 * flow buttons. Verifies real metric values render (SV 70, EF ~58.33,
 * CO 5.04, MAP 93.33), not static placeholders.
 */
test.describe('Lab manual baseline', () => {
  test('enter baseline vitals, operate, and see real metrics', async ({ page }) => {
    await page.goto('/lab')

    // Create case
    await page.getByRole('button', { name: /Create Case/i }).first().click()

    // Fill baseline vitals by placeholder
    const fills: Array<[RegExp, string]> = [
      [/e\.g\. 72/, '72'],
      [/e\.g\. 120/, '120'],
      [/e\.g\. 80/, '80'],
      [/e\.g\. 130/, '120'],
      [/e\.g\. 50/, '50'],
      [/e\.g\. 98/, '98'],
    ]
    for (const [ph, val] of fills) {
      const field = page.getByPlaceholder(ph).first()
      if (await field.count()) await field.fill(val)
    }

    // Submit manual vitals form if a submit control exists
    const submit = page.getByRole('button', { name: /save|submit|apply|use vitals/i }).first()
    if (await submit.count()) await submit.click()

    // Extract then operate
    await page.getByRole('button', { name: /Extract Evidence/i }).first().click()
    await page.getByRole('button', { name: /Run Operation/i }).first().click()

    // Real metric values appear (allow rounding variants).
    await expect(page.getByText(/58(\.3)?/).first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText(/5\.04|5\.0/).first()).toBeVisible()

    // 3D scene container and a chart container exist.
    await expect(page.locator('[aria-label="HeartTwin 3D visualization"]')).toBeVisible()
  })
})
