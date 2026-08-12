const STORAGE_KEY = 'ming_guide_seen'
const PREFERENCE_KEY = 'ming_guide_preference'

export type GuidePreference = 'completed' | 'skipped' | 'never'

export function markGuideSeen(): void {
  try {
    localStorage.setItem(STORAGE_KEY, '1')
  } catch (cause) {
    console.warn('[guide] unable to mark guide seen', cause)
  }
}

export function setGuidePreference(preference: GuidePreference): void {
  try {
    localStorage.setItem(PREFERENCE_KEY, preference)
    if (preference !== 'skipped') localStorage.setItem(STORAGE_KEY, '1')
  } catch (cause) {
    console.warn('[guide] unable to persist preference', cause)
  }
}

export function getGuidePreference(): GuidePreference | null {
  try {
    const value = localStorage.getItem(PREFERENCE_KEY)
    return value === 'completed' || value === 'skipped' || value === 'never' ? value : null
  } catch (cause) {
    console.warn('[guide] unable to read preference', cause)
    return null
  }
}

export function shouldAutoOpenGuide(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== '1' && localStorage.getItem(PREFERENCE_KEY) !== 'never'
  } catch (cause) {
    console.warn('[guide] unable to determine auto-open state', cause)
    return true
  }
}
