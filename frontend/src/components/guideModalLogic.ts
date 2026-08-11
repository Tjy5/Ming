const STORAGE_KEY = 'ming_guide_seen'

export function markGuideSeen(): void {
  try {
    localStorage.setItem(STORAGE_KEY, '1')
  } catch {
    // localStorage may be unavailable in privacy-restricted contexts.
  }
}

export function shouldAutoOpenGuide(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== '1'
  } catch {
    return true
  }
}
