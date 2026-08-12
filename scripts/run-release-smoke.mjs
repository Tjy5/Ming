import { execFileSync, spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import {
  candidateId,
  createReport,
  finishReport,
  runId,
  setStage,
  validateReport,
  writeReport,
} from './release-smoke-report.mjs'

const repoRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const reportRoot = path.join(repoRoot, 'output', 'playwright', 'release-smoke')
const startedAt = new Date().toISOString()
const id = runId()
const required = [
  'MING_LIVE_AI_PROVIDER',
  'MING_LIVE_AI_PROVIDER_TYPE',
  'MING_LIVE_AI_API_KEY',
  'MING_LIVE_AI_BASE_URL',
  'MING_LIVE_AI_MODEL',
]

let candidate
try {
  candidate = candidateId(process.env.MING_RELEASE_CANDIDATE)
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 2
}

const runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'ming-release-smoke-'))
const artifactDir = candidate ? path.join(reportRoot, candidate) : null
const revision = (() => {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' }).trim()
  } catch {
    return null
  }
})()

async function latestReport() {
  if (!artifactDir) return null
  try {
    const entries = await fs.readdir(artifactDir, { withFileTypes: true })
    const reports = []
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith('.json')) continue
      try {
        reports.push(JSON.parse(await fs.readFile(path.join(artifactDir, entry.name), 'utf8')))
      } catch {
        // Invalid reports remain blocking evidence and are ignored for rerun linkage.
      }
    }
    reports.sort((a, b) => String(b.finished_at ?? b.started_at).localeCompare(String(a.finished_at ?? a.started_at)))
    return reports[0] ?? null
  } catch {
    return null
  }
}

async function writeHarnessFailure(errorCode) {
  if (!candidate || !artifactDir) return
  const report = createReport({
    candidate,
    id,
    rerunOf: process.env.MING_LIVE_AI_RERUN_OF || null,
    startedAt,
    revision,
  })
  setStage(report, 'public_browser_gameplay', { status: 'fail', error_code: errorCode })
  finishReport(report, {
    status: 'fail',
    finishedAt: new Date().toISOString(),
    secretScan: validateReport(report, { secret: process.env.MING_LIVE_AI_API_KEY }).errors.every((error) => error !== 'secret_present'),
  })
  await writeReport(artifactDir, report)
}

try {
  if (!candidate) throw new Error('release candidate is required')
  const missing = required.filter((name) => !process.env[name])
  if (missing.length) throw new Error(`missing explicit live smoke configuration: ${missing.join(', ')}`)

  const previous = await latestReport()
  if (previous && process.env.MING_LIVE_AI_RERUN_OF !== previous.run_id) {
    throw new Error(`explicit rerun required: set MING_LIVE_AI_RERUN_OF=${previous.run_id}`)
  }

  const env = {
    ...process.env,
    MING_RELEASE_SMOKE_RUN_ID: id,
    MING_SMOKE_RUN_DIR: runDir,
    MING_RELEASE_SMOKE_REPORT_DIR: artifactDir,
    MING_RELEASE_SMOKE_REVISION: revision ?? '',
  }
  const child = spawn(
    // Windows exposes the npm launcher as npx.cmd; with shell=false an
    // unresolved `npx` otherwise fails before Playwright can print a harness
    // diagnostic, leaving a misleading zero-call browser_harness_failed report.
    process.platform === 'win32' ? 'npx.cmd' : 'npx',
    ['playwright', 'test', 'e2e/release-smoke.spec.mjs', '--config=playwright.config.ts', '--project=desktop'],
    // The Windows npm launcher is a .cmd script and requires shell dispatch
    // in this Node runtime; all arguments here are fixed by the smoke runner.
    { cwd: path.join(repoRoot, 'frontend'), env, stdio: 'inherit', shell: process.platform === 'win32' },
  )
  const exitCode = await new Promise((resolve) => {
    child.once('error', () => resolve(1))
    child.once('exit', (code, signal) => resolve(typeof code === 'number' ? code : (signal ? 1 : 0)))
  })
  if (exitCode !== 0) {
    const entries = await fs.readdir(artifactDir).catch(() => [])
    if (!entries.some((entry) => entry === `${id}.json`)) await writeHarnessFailure('browser_harness_failed')
  }
  process.exitCode = exitCode
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  await writeHarnessFailure('operator_configuration_error')
  process.exitCode = 1
} finally {
  const resolved = path.resolve(runDir)
  if (resolved.startsWith(path.resolve(os.tmpdir(), 'ming-release-smoke-'))) {
    await fs.rm(resolved, { recursive: true, force: true })
  }
}
