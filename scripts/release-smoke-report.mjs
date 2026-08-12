import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'

export const RELEASE_REPORT_VERSION = 1
export const REQUIRED_STAGES = [
  'settings_test',
  'settings_apply',
  'public_browser_gameplay',
  'runtime_identity',
  'structured_adjudication',
  'time_state_settlement',
  'validated_narrative',
  'reload',
]

const SAFE_STATUSES = new Set(['pending', 'pass', 'fail', 'skipped'])

export function candidateId(value) {
  const id = String(value ?? '').trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$/.test(id)) {
    throw new Error('MING_RELEASE_CANDIDATE must be 2-80 safe characters')
  }
  return id
}

export function runId() {
  return `${new Date().toISOString().replaceAll(':', '').replaceAll('.', '')}-${crypto.randomBytes(6).toString('hex')}`
}

export function hostOf(raw) {
  try {
    return new URL(raw).host
  } catch {
    return ''
  }
}

export function configFingerprint(config, secret) {
  const canonical = JSON.stringify({
    provider: config.provider,
    provider_type: config.provider_type,
    model: config.model,
    base_url: config.base_url,
    thinking: config.thinking ?? {},
    api_key: config.api_key,
  })
  return crypto.createHmac('sha256', secret).update(canonical).digest('hex')
}

function safeStage(stage, data = {}) {
  const status = SAFE_STATUSES.has(data.status) ? data.status : 'pending'
  return {
    stage,
    status,
    request_ids: Array.isArray(data.request_ids)
      ? data.request_ids.filter((id) => typeof id === 'string').slice(0, 8)
      : [],
    error_code: typeof data.error_code === 'string' ? data.error_code : null,
  }
}

export function createReport({ candidate, id, rerunOf = null, startedAt, revision = null }) {
  return {
    schema_version: RELEASE_REPORT_VERSION,
    run_id: id,
    release_candidate: candidate,
    rerun_of: rerunOf,
    started_at: startedAt,
    finished_at: null,
    revision,
    status: 'fail',
    provider: {
      provider: null,
      provider_type: null,
      model: null,
      base_url_host: null,
      config_fingerprint: null,
    },
    runtime: {
      profile: 'operator-byok',
      backend_origin: null,
      frontend_origin: null,
      same_config_identity: false,
      fallback_observed: false,
      automatic_retry_observed: false,
    },
    calls: {
      settings_probe: 0,
      settings_apply: 0,
      public_browser_gameplay: 0,
      strict_runtime_action: 0,
      provider_generations: null,
      input_tokens: null,
      output_tokens: null,
    },
    stages: REQUIRED_STAGES.map((stage) => safeStage(stage)),
    summary: {
      discovered: REQUIRED_STAGES.length,
      ran: 0,
      passed: 0,
      failed: 0,
      skipped: 0,
    },
    artifacts: {
      directory: 'output/playwright/release-smoke',
      failure_screenshot: null,
    },
    secret_scan: { passed: true },
  }
}

export function setStage(report, stage, data = {}) {
  const index = report.stages.findIndex((item) => item.stage === stage)
  if (index < 0) throw new Error(`unknown release smoke stage: ${stage}`)
  report.stages[index] = safeStage(stage, data)
  const counts = { ran: 0, passed: 0, failed: 0, skipped: 0 }
  for (const item of report.stages) {
    if (item.status === 'pending') continue
    counts.ran += 1
    if (item.status === 'pass') counts.passed += 1
    if (item.status === 'fail') counts.failed += 1
    if (item.status === 'skipped') counts.skipped += 1
  }
  report.summary = { discovered: REQUIRED_STAGES.length, ...counts }
}

export function finishReport(report, { status, finishedAt, secretScan = true, failureScreenshot = null }) {
  report.status = status === 'pass' ? 'pass' : 'fail'
  report.finished_at = finishedAt
  report.secret_scan = { passed: secretScan }
  report.artifacts.failure_screenshot = failureScreenshot
  return report
}

export function validateReport(report, { secret = null } = {}) {
  const errors = []
  if (!report || report.schema_version !== RELEASE_REPORT_VERSION) errors.push('schema_version')
  if (!report?.run_id || !report?.release_candidate) errors.push('identity')
  if (!Array.isArray(report?.stages) || report.stages.length !== REQUIRED_STAGES.length) {
    errors.push('stages')
  } else {
    const names = report.stages.map((stage) => stage.stage)
    if (JSON.stringify(names) !== JSON.stringify(REQUIRED_STAGES)) errors.push('stage_names')
    for (const stage of report.stages) {
      if (!SAFE_STATUSES.has(stage.status)) errors.push(`stage_status:${stage.stage}`)
    }
  }
  const allPass = report?.stages?.every((stage) => stage.status === 'pass')
  if (report?.status !== 'pass' || !allPass) errors.push('release_blocked')
  if (report?.summary?.discovered !== REQUIRED_STAGES.length
    || report?.summary?.ran !== REQUIRED_STAGES.length
    || report?.summary?.passed !== REQUIRED_STAGES.length
    || report?.summary?.failed !== 0
    || report?.summary?.skipped !== 0) {
    errors.push('summary')
  }
  if (report?.runtime?.fallback_observed || report?.runtime?.automatic_retry_observed) {
    errors.push('fallback_or_retry')
  }
  if (report?.secret_scan?.passed !== true) errors.push('secret_scan')
  if (secret && JSON.stringify(report).includes(secret)) errors.push('secret_present')
  return { ok: errors.length === 0, errors }
}

export async function writeReport(directory, report) {
  const reportPath = path.join(directory, `${report.run_id}.json`)
  await fs.mkdir(directory, { recursive: true })
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  return reportPath
}
