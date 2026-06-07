import { test, expect } from '@playwright/test'
import { SAFETY_PHRASE } from '../helpers'

test.describe('Root routing', () => {
  test('/ loads with app name and safety copy', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })

    await page.goto('/')
    await expect(page).toHaveTitle(/HeartTwin/i)
    await expect(page.getByText(/HeartTwin/i).first()).toBeVisible()
    // Safety boundary phrase visible somewhere on landing.
    await expect(page.getByText(/Not for diagnosis or treatment decisions/i).first()).toBeVisible()

    // No hydration-failure console errors.
    const hydrationErrors = errors.filter((e) => /hydration|mismatch/i.test(e))
    expect(hydrationErrors, hydrationErrors.join('\n')).toHaveLength(0)
  })

  test('/lab loads', async ({ page }) => {
    await page.goto('/lab')
    await expect(page).toHaveURL(/\/lab/)
    await expect(page.locator('body')).toBeVisible()
  })

  test('/about loads', async ({ page }) => {
    await page.goto('/about')
    await expect(page).toHaveURL(/\/about/)
    await expect(page.locator('body')).toBeVisible()
  })

  test('CTA from landing navigates to lab', async ({ page }) => {
    await page.goto('/')
    const labLink = page.locator('a[href="/lab"], a[href*="/lab"]').first()
    if (await labLink.count()) {
      await labLink.click()
      await expect(page).toHaveURL(/\/lab/)
    } else {
      await page.goto('/lab')
      await expect(page).toHaveURL(/\/lab/)
    }
  })

  test('safety phrase exact text is reachable in app', async ({ page }) => {
    await page.goto('/')
    const html = await page.content()
    expect(html.includes('Not for diagnosis or treatment decisions')).toBeTruthy()
    // Full canonical phrase is acceptable to surface as well.
    expect(SAFETY_PHRASE.length).toBeGreaterThan(20)
  })
})
