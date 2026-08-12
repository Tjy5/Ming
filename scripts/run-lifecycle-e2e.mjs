import { spawn } from 'node:child_process'
import process from 'node:process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Deterministic browser evidence is an explicit gate.  The backend launcher
// installs the fake provider only for this process and uses an isolated DB;
// product startup never selects this profile implicitly.
const repoRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const frontendRoot = path.join(repoRoot, 'frontend')
const env = { ...process.env, MING_E2E_MODE: 'offline' }
const command = process.platform === 'win32' ? 'npx.cmd' : 'npx'
const child = spawn(
  command,
  ['playwright', 'test', '--config=playwright.config.ts', '--project=desktop'],
  { cwd: frontendRoot, env, stdio: 'inherit', shell: process.platform === 'win32' },
)

child.once('error', () => { process.exitCode = 1 })
child.once('exit', (code, signal) => {
  process.exitCode = typeof code === 'number' ? code : (signal ? 1 : 0)
})
