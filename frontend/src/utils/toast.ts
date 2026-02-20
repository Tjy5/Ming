export const isAbortError = (e: unknown): boolean =>
  e instanceof Error && e.name === 'AbortError';

export const showCancelToast = (showToast: (msg: string) => void) => {
  showToast('操作已取消');
};
