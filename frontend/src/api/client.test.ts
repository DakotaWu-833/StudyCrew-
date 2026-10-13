import { afterEach, describe, expect, it, vi } from "vitest";
import { APIError, apiFetch, apiFetchAll, apiFetchBlob, cookie, errorMessage, fieldErrors } from "./client";

describe("API client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads a named cookie without exposing other cookies", () => {
    Object.defineProperty(document, "cookie", { writable: true, value: "csrftoken=abc123; theme=light" });
    expect(cookie("csrftoken")).toBe("abc123");
    expect(cookie("missing")).toBe("");
  });

  it("adds JSON and CSRF headers to mutations", async () => {
    Object.defineProperty(document, "cookie", { writable: true, value: "csrftoken=safe-token" });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "1" }), { status: 201, headers: { "Content-Type": "application/json" } }),
    );
    await apiFetch("/api/v1/projects/", { method: "POST", body: JSON.stringify({ name: "Demo" }) });
    const request = fetchMock.mock.calls[0];
    expect(request?.[1]?.credentials).toBe("same-origin");
    expect(new Headers(request?.[1]?.headers).get("X-CSRFToken")).toBe("safe-token");
  });

  it("turns structured error responses into APIError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "validation_error", message: "Check fields", fields: { name: ["Required"] } } }), { status: 400 }),
    );
    await expect(apiFetch("/api/v1/projects/")).rejects.toMatchObject<Partial<APIError>>({
      status: 400,
      code: "validation_error",
      message: "Check fields",
    });
  });

  it("accepts authenticated binary previews and JSON permission errors without caching", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("preview", { headers: { "Content-Type": "text/plain", "X-Preview-Truncated": "true" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "not_found", message: "File unavailable." } }), { status: 404 }));
    const result = await apiFetchBlob("/api/v1/files/preview/");
    expect(await result.blob.text()).toBe("preview");
    expect(result.truncated).toBe(true);
    const options = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(options?.headers).get("Accept")).toBe("*/*");
    expect(options?.cache).toBe("no-store");
    expect(options?.credentials).toBe("same-origin");
    await expect(apiFetchBlob("/api/v1/files/preview/")).rejects.toMatchObject({ status: 404, message: "File unavailable." });
  });

  it("loads every same-origin result page without hiding later records", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ count: 2, next: "/api/v1/tasks/?page=2", previous: null, results: [{ id: "1" }] })),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ count: 2, next: null, previous: "/api/v1/tasks/", results: [{ id: "2" }] })),
      );

    const page = await apiFetchAll<{ id: string }>("/api/v1/tasks/");

    expect(page.results).toEqual([{ id: "1" }, { id: "2" }]);
    expect(page.count).toBe(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/tasks/?page=2");
  });

  it("turns API field errors into actionable form feedback", () => {
    const error = new APIError(400, {
      error: {
        message: "Please correct the highlighted fields.",
        fields: { time_zone: ["Enter a valid IANA time zone."] },
      },
    });

    expect(errorMessage(error)).toBe(
      "Please correct these fields. Time zone: Enter a valid IANA time zone.",
    );
  });

  it("retains named validation messages for inline field feedback", () => {
    const error = new APIError(400, { error: { fields: {
      display_name: ["Required.", "Use at least two characters."],
      time_zone: "Choose a valid zone.",
    } } });
    expect(fieldErrors(error)).toEqual({ display_name: "Required. Use at least two characters.", time_zone: "Choose a valid zone." });
    expect(fieldErrors(new Error("Offline"))).toEqual({});
    expect(fieldErrors(undefined)).toEqual({});
  });
});
