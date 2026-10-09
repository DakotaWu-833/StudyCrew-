const prefix = "studycrew:draft:";
export const draftLifetime = 24 * 60 * 60 * 1000;
export interface StoredDraft { savedAt: number; values: Record<string, string> }
export function draftKey(user: string, scope: string) { return `${prefix}${user}:${scope}`; }
export function loadDraft(user: string, scope: string): StoredDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(user, scope)); if (!raw) return null;
    const data = JSON.parse(raw) as StoredDraft;
    if (!data || typeof data.savedAt !== "number" || Date.now() - data.savedAt > draftLifetime || typeof data.values !== "object" || !data.values) { localStorage.removeItem(draftKey(user, scope)); return null; }
    return data;
  } catch { return null; }
}
export function saveDraft(user: string, scope: string, values: Record<string, string>) {
  try { localStorage.setItem(draftKey(user, scope), JSON.stringify({ savedAt: Date.now(), values })); } catch { /* Storage can be unavailable in private browsing. */ }
}
export function clearDraft(user: string, scope: string) { try { localStorage.removeItem(draftKey(user, scope)); } catch { /* Optional local storage. */ } }
export function clearUserDrafts(user: string) {
  try { for (const key of Object.keys(localStorage)) if (key.startsWith(`${prefix}${user}:`)) localStorage.removeItem(key); } catch { /* Optional local storage. */ }
}
export function pruneDrafts() {
  try { for (const key of Object.keys(localStorage)) if (key.startsWith(prefix)) {
    try { const data = JSON.parse(localStorage.getItem(key) ?? "null") as StoredDraft; if (!data || Date.now() - data.savedAt > draftLifetime) localStorage.removeItem(key); }
    catch { localStorage.removeItem(key); }
  } } catch { /* Optional local storage. */ }
}
