import { afterEach, describe, expect, it, vi } from "vitest";
import { meetingApi } from "./resources";

const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), {
  status: 200, headers: { "Content-Type": "application/json" },
});

describe("meeting pagination contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("fetches only a single five-record page with encoded filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ count: 12, next: "/next", previous: null, results: [] }));
    const page = await meetingApi.listPage("project-id", { scope: "all", state: "ended", search: "  review & plans  ", page: 2 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/meetings/?project=project-id&scope=all&state=ended&search=review+%26+plans&page=2&page_size=5");
    expect(page.count).toBe(12);
  });

  it("keeps the full-list contract for dashboard callers and follows pagination", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ count: 2, next: "/api/v1/meetings/?project=project-id&scope=active&page_size=50&page=2", previous: null, results: [{ id: "first" }] }))
      .mockResolvedValueOnce(jsonResponse({ count: 2, next: null, previous: "/previous", results: [{ id: "second" }] }));
    const page = await meetingApi.list("project-id");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/meetings/?project=project-id&scope=active&page_size=50");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/meetings/?project=project-id&scope=active&page_size=50&page=2");
    expect(page.results.map((meeting) => meeting.id)).toEqual(["first", "second"]);
    expect(page.next).toBeNull();
  });
});
