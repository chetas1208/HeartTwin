import { test, expect } from '@playwright/test'
import { apiBase, assertNoSecretLeak } from '../helpers'

test.describe('Health and config', () => {
  test('GET /api/v1/health returns ok', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/health`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.status).toBe('ok')
  })

  test('GET /api/v1/config returns safe config with no secrets', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/config`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()

    expect(body.app_name).toBe('HeartTwin Lab')
    expect(body.api_base).toBe('/api/v1')
    expect(body.models).toBeTruthy()
    for (const k of ['intake', 'extraction', 'validator', 'state_builder',
      'electrophysiology', 'hemodynamics', 'recovery', 'evaluator']) {
      expect(body.models[k]).toBeTruthy()
    }

    const text = JSON.stringify(body)
    // No secret-looking substrings.
    expect(assertNoSecretLeak(text)).toEqual([])
    for (const k of ['OPENAI_API_KEY', 'WANDB_API_KEY', 'UPSTASH_REDIS_REST_TOKEN',
      'BLOB_READ_WRITE_TOKEN', 'VISTA3D_API_KEY']) {
      // The raw env var *value* must never be present; here we just ensure no
      // obviously-secret key/value pair is serialized.
      expect(text).not.toContain(`"${k}"`)
    }
  })

  test('system-check reports honest integration status', async ({ request, baseURL }) => {
    const res = await request.get(`${apiBase(baseURL)}/system-check`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(['ok', 'warning', 'failed']).toContain(body.status)
    expect(Array.isArray(body.checks)).toBeTruthy()
    expect(body.metrics).toBeTruthy()
    expect(body.integrations).toBeTruthy()
    expect(['configured', 'local_fallback', 'error']).toContain(body.integrations.weave)
  })
})
