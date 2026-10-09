import { beforeEach, describe, expect, it, vi } from "vitest";
import { campusApi } from "./campus";
import { apiFetch } from "./client";

vi.mock("./client", () => ({ apiFetch: vi.fn(), jsonBody: (value: unknown) => ({ body: JSON.stringify(value) }) }));

describe("academic workflow API", () => {
  beforeEach(() => { vi.mocked(apiFetch).mockReset().mockResolvedValue({}); });
  it("encodes search text without expanding its permissions or query parameters", async () => {
    await campusApi.search("report & project=private");
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/campus/search/?q=report+%26+project%3Dprivate&page=1");
  });
  it("sends the current checklist revision for explicit member confirmation", async () => {
    await campusApi.projectAction("project-id", "submission/confirm/", { revision: 7 });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/campus/projects/project-id/submission/confirm/", { method: "POST", body: '{"revision":7}' });
  });
  it("requests approval rather than granting membership from the browser", async () => {
    await campusApi.action("join/", { token: "example-code" });
    expect(apiFetch).toHaveBeenCalledWith("/api/v1/campus/join/", { method: "POST", body: '{"token":"example-code"}' });
  });
});
