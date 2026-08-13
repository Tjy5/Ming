import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { isAbsolute, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'

const evidenceDirectory = process.env.MING_VISUAL_EVIDENCE_DIR
const captureLabel = process.env.MING_VISUAL_CAPTURE_LABEL
const viewports = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]
const landmarks = {
  resourceBar: '.resource-bar',
  mapWorkspace: '.map-workspace',
  map: '.geographic-map',
  rightPanel: '.right-panel',
  bottomPanel: '.bottom-panel',
  eventBar: '.event-bar',
  commandSurface: '.action-area, .trpg-entry-panel',
}
const closedSurfaces = {
  guide: '[data-testid="guide-modal"]',
  inspector: '.region-inspector',
  resourceDetail: '.resource-details-popover',
  decree: '.edict-panel',
  courtDialog: '.assembly-modal',
}
const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const taskRoot = resolve(frontendRoot, '..', '..', '.trellis', 'tasks')

function resolveEvidenceDirectory(directory) {
  if (!isAbsolute(directory)) {
    throw new Error('MING_VISUAL_EVIDENCE_DIR must be an absolute task research directory')
  }

  const resolved = resolve(directory)
  const relativePath = relative(taskRoot, resolved)
  const pathSegments = relativePath.split(sep)
  const isTaskResearchDirectory = relativePath
    && !relativePath.startsWith(`..${sep}`)
    && relativePath !== '..'
    && pathSegments.length === 2
    && pathSegments[1] === 'research'

  if (!isTaskResearchDirectory) {
    throw new Error('MING_VISUAL_EVIDENCE_DIR must be a task-local .trellis/tasks/*/research directory')
  }
  return resolved
}

test.describe('deterministic desktop visual capture @visual', () => {
  test.beforeAll(async () => {
    if (!evidenceDirectory) throw new Error('MING_VISUAL_EVIDENCE_DIR is required')
    if (!['before', 'after'].includes(captureLabel)) {
      throw new Error('MING_VISUAL_CAPTURE_LABEL must be either "before" or "after"')
    }
    await mkdir(resolveEvidenceDirectory(evidenceDirectory), { recursive: true })
  })

  for (const viewport of viewports) {
    test(`${viewport.width}x${viewport.height}`, async ({ browser }, testInfo) => {
      const context = await browser.newContext({
        viewport,
        reducedMotion: 'reduce',
        deviceScaleFactor: 1,
      })
      const page = await context.newPage()
      const consoleErrors = []
      const pageErrors = []
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      page.on('pageerror', (error) => pageErrors.push(error.message))

      await page.addInitScript(() => {
        localStorage.setItem('ming_guide_seen', '1')
      })
      const response = await page.request.post('http://127.0.0.1:8000/api/game/new')
      expect(response.ok()).toBe(true)
      const initialState = await response.json()

      await page.goto('/')
      await expect(page.locator('.game-layout')).toBeVisible()
      await expect(page.locator('.geographic-map svg')).toBeVisible()
      await page.evaluate(async () => {
        await document.fonts.ready
        await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
      })

      const rectangles = {}
      for (const [name, selector] of Object.entries(landmarks)) {
        const box = await page.locator(selector).boundingBox()
        expect(box, `${name} landmark must be visible`).not.toBeNull()
        rectangles[name] = box
      }
      const openSurfaces = {}
      for (const [name, selector] of Object.entries(closedSurfaces)) {
        openSurfaces[name] = await page.locator(selector).count()
      }
      expect(openSurfaces).toEqual(Object.fromEntries(Object.keys(closedSurfaces).map((name) => [name, 0])))

      const dimensions = await page.evaluate(() => ({
        document: {
          clientWidth: document.documentElement.clientWidth,
          clientHeight: document.documentElement.clientHeight,
          scrollWidth: document.documentElement.scrollWidth,
          scrollHeight: document.documentElement.scrollHeight,
        },
        body: {
          clientWidth: document.body.clientWidth,
          clientHeight: document.body.clientHeight,
          scrollWidth: document.body.scrollWidth,
          scrollHeight: document.body.scrollHeight,
        },
        devicePixelRatio: window.devicePixelRatio,
      }))
      expect(dimensions.document.clientWidth).toBe(viewport.width)
      expect(dimensions.document.clientHeight).toBe(viewport.height)
      expect(dimensions.body.clientWidth).toBe(viewport.width)
      expect(dimensions.body.clientHeight).toBe(viewport.height)
      expect(dimensions.document.scrollWidth).toBe(dimensions.document.clientWidth)
      expect(dimensions.document.scrollHeight).toBe(dimensions.document.clientHeight)

      const stem = `baseline-${viewport.width}x${viewport.height}-${captureLabel}`
      const outputDirectory = resolveEvidenceDirectory(evidenceDirectory)
      const screenshotPath = resolve(outputDirectory, `${stem}.png`)
      await page.screenshot({ path: screenshotPath, animations: 'disabled' })
      const screenshotSha256 = createHash('sha256').update(await readFile(screenshotPath)).digest('hex')
      const metadata = {
        schemaVersion: 1,
        capturedAt: new Date().toISOString(),
        captureLabel,
        command: 'npm run capture:visual',
        project: testInfo.project.name,
        browser: {
          name: browser.browserType().name(),
          version: browser.version(),
        },
        url: page.url(),
        apiUrl: 'http://127.0.0.1:8000/api',
        viewport,
        zoomPercent: 100,
        reducedMotion: true,
        localStorage: { ming_guide_seen: '1' },
        fixture: {
          server: 'backend/scripts/lifecycle_e2e_server.py',
          provider: 'tests.fakes.FakeProvider',
          initialization: 'POST /api/game/new',
          gameId: initialState.world_metadata?.game_id,
          branchId: initialState.world_metadata?.branch_id,
          versionId: initialState.world_metadata?.version_id,
          phase: initialState.phase,
          time: initialState.time,
          resources: {
            nationalTreasury: initialState.national_treasury,
            imperialTreasury: initialState.imperial_treasury,
            grain: initialState.grain,
            population: initialState.population,
            militaryStrength: initialState.military_strength,
            civilMorale: initialState.civil_morale,
            militaryMorale: initialState.military_morale,
            courtPrestige: initialState.court_prestige,
          },
        },
        openSurfaces,
        rectangles,
        dimensions,
        consoleErrors,
        pageErrors,
        screenshot: `${stem}.png`,
        screenshotSha256,
      }
      await writeFile(resolve(outputDirectory, `${stem}.json`), `${JSON.stringify(metadata, null, 2)}\n`, 'utf8')

      expect(consoleErrors).toEqual([])
      expect(pageErrors).toEqual([])
      await context.close()
    })
  }
})
