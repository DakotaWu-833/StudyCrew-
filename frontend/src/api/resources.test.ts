import { afterEach, describe, expect, it, vi } from "vitest";
import { meetingApi, projectApi, taskApi } from "./resources";

const jsonResponse = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });

describe("resource API paths", () => {
  afterEach(() => vi.restoreAllMocks());

  it("encodes task filters instead of interpolating untrusted query text", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ count: 0, next: null, previous: null, results: [] }),
    );
    await taskApi.list("project-id", { q: "research & review", status: "blocked" });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/tasks/?project=project-id&q=research+%26+review&status=blocked",
    );
  });

  it("uses a project-scoped insights endpoint and explicit date parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
    await projectApi.insights("project-id", {
      range_start: "2026-09-01",
      range_end: "2026-09-14",
      event_type: "task_created",
    });
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/api/v1/projects/project-id/insights/?range_start=2026-09-01&range_end=2026-09-14&event_type=task_created",
    );
  });

  it("sends RSVP changes through the dedicated action endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
    await meetingApi.rsvp("meeting-id", "accepted", "Can join after 3 pm");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/meetings/meeting-id/rsvp/");
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      response: "accepted",
      availability_note: "Can join after 3 pm",
    });
  });
});
