import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import process from 'node:process'
import { test, expect } from '@playwright/test'
import {
  configFingerprint,
  createReport,
  finishReport,
  setStage,
  writeReport,
} from '../../scripts/release-smoke-report.mjs'

const required = [
  'MING_RELEASE_CANDIDATE',
  'MING_LIVE_AI_PROVIDER',
  'MING_LIVE_AI_PROVIDER_TYPE',
  'MING_LIVE_AI_API_KEY',
  'MING_LIVE_AI_BASE_URL',
  'MING_LIVE_AI_MODEL',
]

function env(name) {
  const value = process.env[name]
  if (!value) throw Object.assign(new Error(`missing ${name}`), { code: 'operator_configuration_error' })
  return value
}

function safeConfig(payload) {
  const config = payload?.verified_config ?? payload ?? {}
  return {
    provider: typeof config.provider === 'string' ? config.provider : null,
    provider_type: typeof config.provider_type === 'string' ? config.provider_type : null,
    model: typeof config.model === 'string' ? config.model : null,
    base_url: typeof config.base_url === 'string' ? config.base_url : null,
    thinking: config.thinking_config ?? config.thinking ?? {},
  }
}

async function responseBody(response) {
  const body = await response.json().catch(() => null)
  if (!response.ok()) {
    const code = body?.detail?.error_code ?? body?.error_code ?? 'http_error'
    throw Object.assign(new Error(code), { code })
  }
  return body
}

test.describe('release candidate BYOK runtime smoke', () => {
  test('settings → public gameplay → strict runtime action → reload', async ({ page }) => {
    const candidate = env('MING_RELEASE_CANDIDATE')
    for (const name of required.slice(1)) env(name)
    const apiKey = process.env.MING_LIVE_AI_API_KEY
    const reportDir = env('MING_RELEASE_SMOKE_REPORT_DIR')
    const report = createReport({
      candidate,
      id: env('MING_RELEASE_SMOKE_RUN_ID'),
      rerunOf: process.env.MING_LIVE_AI_RERUN_OF || null,
      startedAt: new Date().toISOString(),
      revision: process.env.MING_RELEASE_SMOKE_REVISION || null,
    })
    const fingerprintSecret = crypto.randomBytes(32)
    const stage = async (name, action) => {
      try {
        await action()
        setStage(report, name, { status: 'pass' })
      } catch (error) {
        setStage(report, name, {
          status: 'fail',
          error_code: error?.code || 'stage_failed',
          request_ids: error?.requestId ? [error.requestId] : [],
        })
        throw error
      }
    }

    try {
      await page.goto('/')
      const settingsButton = page.getByTestId('ai-settings-open')
      // Wait for the initial GET /state to resolve.  Calling /game/new here
      // would require an already-effective provider and would make the BYOK
      // setup flow impossible on a fresh isolated run.
      await expect(settingsButton).toBeVisible({ timeout: 15_000 })
      await settingsButton.click()
      const dialog = page.getByRole('dialog', { name: 'AI 设置' })
      await expect(dialog).toBeVisible()

      const provider = env('MING_LIVE_AI_PROVIDER')
      const providerOptions = ['openai', 'google', 'h', 'Z']
      const providerSelect = dialog.locator('label').filter({ hasText: '供应商' }).locator('select').first()
      const providerTypeSelect = dialog.locator('label').filter({ hasText: 'Provider Type' }).locator('select').first()
      if (providerOptions.includes(provider)) {
        await providerSelect.selectOption(provider)
      } else {
        await providerSelect.selectOption('custom')
        await dialog.getByLabel('自定义标识').fill(provider)
      }
      await providerTypeSelect.selectOption(env('MING_LIVE_AI_PROVIDER_TYPE'))
      await dialog.getByLabel('API Key').fill(apiKey)
      await dialog.getByLabel('Base URL').fill(env('MING_LIVE_AI_BASE_URL'))
      await dialog.getByLabel('主模型').first().fill(env('MING_LIVE_AI_MODEL'))

      let testResult
      await stage('settings_test', async () => {
        const responsePromise = page.waitForResponse((response) => (
          response.url().endsWith('/api/settings/ai/test') && response.request().method() === 'POST'
        ))
        await dialog.getByRole('button', { name: '测试连接（1 次）' }).click()
        testResult = await responseBody(await responsePromise)
        report.calls.settings_probe = 1
        const config = safeConfig(testResult)
        report.provider = {
          provider: config.provider,
          provider_type: config.provider_type,
          model: config.model,
          base_url_host: new URL(config.base_url).host,
          config_fingerprint: configFingerprint({ ...config, api_key: apiKey }, fingerprintSecret),
        }
        report.runtime.backend_origin = 'http://127.0.0.1:8000'
        if (!testResult.verification_token || !testResult.request_id) {
          throw Object.assign(new Error('test_missing_verification'), { code: 'invalid_response' })
        }
      })

      let applyResult
      await stage('settings_apply', async () => {
        const responsePromise = page.waitForResponse((response) => (
          response.url().endsWith('/api/settings/ai') && response.request().method() === 'POST'
        ))
        await dialog.getByRole('button', { name: '保存并应用' }).click()
        applyResult = await responseBody(await responsePromise)
        report.calls.settings_apply = 1
        const applied = safeConfig(applyResult)
        report.runtime.same_config_identity = (
          applied.provider === report.provider.provider
          && applied.provider_type === report.provider.provider_type
          && applied.model === report.provider.model
          && new URL(applied.base_url).host === report.provider.base_url_host
        )
        if (!report.runtime.same_config_identity) {
          throw Object.assign(new Error('settings_runtime_identity_mismatch'), { code: 'runtime_identity_mismatch' })
        }
      })

      await stage('public_browser_gameplay', async () => {
        const input = page.getByPlaceholder(/自由行动/)
        await expect(input).toBeEnabled({ timeout: 120_000 })
        const actionResponse = page.waitForResponse((response) => (
          response.url().endsWith('/api/trpg/act') && response.request().method() === 'POST'
        ), { timeout: 120_000 })
        await input.fill('在河港建立一条不依赖旧势力的商路')
        await page.getByRole('button', { name: '行动' }).click()
        const body = await responseBody(await actionResponse)
        report.calls.public_browser_gameplay = 1
        if (body.source !== 'ai' || body.narrative_status === 'fallback_facts') {
          throw Object.assign(new Error('gameplay_fallback_observed'), { code: 'fallback_observed' })
        }
        if (!body.settlement_id || !body.context_version_id) {
          throw Object.assign(new Error('gameplay_missing_commit_identity'), { code: 'invalid_response' })
        }
        setStage(report, 'validated_narrative', {
          status: body.narrative_status === 'validated' ? 'pass' : 'fail',
          request_ids: body.narrative_request_id ? [body.narrative_request_id] : [],
          error_code: body.narrative_status === 'validated' ? null : 'narrative_not_validated',
        })
      })

      let strictResult
      let beforeState
      await stage('structured_adjudication', async () => {
        beforeState = await page.evaluate(async () => {
          const response = await fetch('http://127.0.0.1:8000/api/state')
          if (!response.ok) throw Object.assign(new Error('state_unavailable'), { code: 'state_unavailable' })
          return response.json()
        })
        const metadata = beforeState.world_metadata
        if (!metadata?.game_id || !metadata?.branch_id || !metadata?.version_id) {
          throw Object.assign(new Error('world_identity_missing'), { code: 'runtime_identity_missing' })
        }
        strictResult = await page.evaluate(async (state) => {
          const intent = {
            schema_version: 1,
            game_id: state.world_metadata.game_id,
            branch_id: state.world_metadata.branch_id,
            expected_parent_version_id: state.world_metadata.version_id,
            client_action_id: crypto.randomUUID(),
            raw_text: '向北方商旅开放一处新的渡口',
            action_kind: 'release_smoke_free_action',
            mode: state.phase,
          }
          const response = await fetch('http://127.0.0.1:8000/api/actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(intent),
          })
          const body = await response.json().catch(() => null)
          if (!response.ok) {
            throw Object.assign(new Error(body?.detail?.error_code || 'action_failed'), {
              code: body?.detail?.error_code || 'action_failed',
            })
          }
          return body
        }, beforeState)
        report.calls.strict_runtime_action = 1
        const requestId = strictResult?.result?.facts?.attribution?.provider?.request_id
        setStage(report, 'runtime_identity', { status: 'pass', request_ids: requestId ? [requestId] : [] })
      })

      await stage('time_state_settlement', async () => {
        const facts = strictResult?.result?.facts
        const nextState = strictResult?.state
        if (!facts?.time_plan || !facts.result_version_id || !nextState?.world_metadata?.version_id) {
          throw Object.assign(new Error('settlement_missing_time_or_version'), { code: 'invalid_response' })
        }
        if (facts.result_version_id !== nextState.world_metadata.version_id) {
          throw Object.assign(new Error('settlement_version_mismatch'), { code: 'runtime_identity_mismatch' })
        }
        setStage(report, 'structured_adjudication', { status: 'pass' })
      })

      await stage('reload', async () => {
        await page.reload()
        const reloaded = await page.evaluate(async () => {
          const response = await fetch('http://127.0.0.1:8000/api/state')
          if (!response.ok) throw Object.assign(new Error('reload_failed'), { code: 'reload_failed' })
          return response.json()
        })
        if (reloaded.world_metadata?.version_id !== strictResult.result.version.version_id) {
          throw Object.assign(new Error('reload_version_mismatch'), { code: 'reload_mismatch' })
        }
      })

      report.runtime.frontend_origin = new URL(page.url()).origin
      finishReport(report, { status: 'pass', finishedAt: new Date().toISOString() })
    } catch (error) {
      if (error?.code === 'fallback_observed') report.runtime.fallback_observed = true
      finishReport(report, { status: 'fail', finishedAt: new Date().toISOString() })
      throw error
    } finally {
      const serialized = JSON.stringify(report)
      if (apiKey && serialized.includes(apiKey)) {
        report.secret_scan = { passed: false }
        report.status = 'fail'
      }
      await fs.mkdir(reportDir, { recursive: true })
      await writeReport(reportDir, report)
    }
  })
})
