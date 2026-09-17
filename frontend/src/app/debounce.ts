export function scheduleDebounced(callback: () => void, delay = 300): () => void {
  const timer = window.setTimeout(callback, delay);
  return () => window.clearTimeout(timer);
}
