import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { candidateId, validateReport } from './release-smoke-report.mjs'

const candidateArg = process.argv.find((arg) => arg.startsWith('--candidate='))
const rawCandidate = candidateArg ? candidateArg.slice('--candidate='.length) : process.env.MING_RELEASE_CANDIDATE
let candidate
try {
  candidate = candidateId(rawCandidate)
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 2
}

if (candidate) {
  const repoRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
  const root = path.join(repoRoot, 'output', 'playwright', 'release-smoke', candidate)
  let entries = []
  let readFailed = false
  try {
    entries = await fs.readdir(root, { withFileTypes: true })
  } catch {
    console.error(`release blocked: no smoke artifacts for ${candidate}`)
    readFailed = true
    process.exitCode = 1
  }

  if (readFailed) {
    // The missing directory is already a blocking condition.
  } else if (!entries.length) {
    console.error(`release blocked: no smoke artifacts for ${candidate}`)
    process.exitCode = 1
  } else {
    const reports = []
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith('.json')) continue
      try {
        const report = JSON.parse(await fs.readFile(path.join(root, entry.name), 'utf8'))
        reports.push(report)
      } catch {
        // Invalid artifacts are retained as evidence and cannot satisfy the gate.
      }
    }
    reports.sort((a, b) => String(b.finished_at ?? b.started_at).localeCompare(String(a.finished_at ?? a.started_at)))
    const latest = reports[0]
    if (!latest) {
      console.error(`release blocked: no valid smoke report for ${candidate}`)
      process.exitCode = 1
    } else {
      const result = validateReport(latest)
      const previous = reports[1]
      if (previous && latest.rerun_of !== previous.run_id) {
        result.ok = false
        result.errors.push('rerun_provenance')
      }
      if (!result.ok) {
        console.error(`release blocked: ${candidate}: ${result.errors.join(', ')}`)
        process.exitCode = 1
      } else {
        console.log(`release smoke passed: ${candidate} (${latest.run_id})`)
      }
    }
  }
}
