// @vitest-environment node
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";

function worker() {
  const handlers: Record<string, (event: any) => void> = {};
  const cache = { put: vi.fn(), keys: vi.fn(async () => []), delete: vi.fn() };
  const caches = { keys: vi.fn(async () => ["studycrew-static-old", "unrelated"]), delete: vi.fn(), open: vi.fn(async () => cache), match: vi.fn() };
  const fetch = vi.fn(async () => new Response("network"));
  const self = { location: { origin: "https://study.example" }, addEventListener: (name: string, callback: (event: any) => void) => { handlers[name] = callback; }, skipWaiting: vi.fn(), clients: { claim: vi.fn() } };
  runInNewContext(readFileSync(new URL("../../web/service-worker.js", import.meta.url), "utf8"), { self, caches, fetch, Response, URL });
  function request(path: string, mode = "cors", method = "GET") { const event = { request: { url: `https://study.example${path}`, method, mode }, respondWith: vi.fn() }; handlers.fetch!(event); return event; }
  return { request, handlers, fetch, cache, caches, self };
}

it("never intercepts or caches private APIs, photos, authentication or writes", () => {
  const w = worker();
  for (const path of ["/api/v1/accounts/me/", "/media/avatar.jpg", "/account/login/", "/app/projects/private/"]) expect(w.request(path).respondWith).not.toHaveBeenCalled();
  expect(w.request("/static/workspace/main.js", "cors", "POST").respondWith).not.toHaveBeenCalled();
  expect(w.fetch).not.toHaveBeenCalled(); expect(w.caches.open).not.toHaveBeenCalled();
});

it("navigation failures return a generic offline page and never a saved student page", async () => {
  const w = worker(); w.fetch.mockRejectedValue(new Error("offline"));
  const event = w.request("/app/projects/private/", "navigate");
  const response = await event.respondWith.mock.calls[0]![0] as Response;
  expect(response.status).toBe(503); expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(await response.text()).toContain("You are offline"); expect(w.caches.match).not.toHaveBeenCalled();
});

it("uses only the requested public static asset on a network failure", async () => {
  const w = worker(); w.fetch.mockRejectedValue(new Error("offline")); w.caches.match.mockResolvedValue(new Response("public script"));
  const event = w.request("/static/workspace/assets/CalendarPage-abc.js");
  const response = await event.respondWith.mock.calls[0]![0] as Response;
  expect(await response.text()).toBe("public script"); expect(w.caches.match).toHaveBeenCalledWith(event.request);
});

it("removes only previous StudyCrew cache versions during activation", async () => {
  const w = worker(); const event = { waitUntil: vi.fn() }; w.handlers.activate!(event); await event.waitUntil.mock.calls[0]![0];
  expect(w.caches.delete).toHaveBeenCalledExactlyOnceWith("studycrew-static-old"); expect(w.self.clients.claim).toHaveBeenCalled();
});
