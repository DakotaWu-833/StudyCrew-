import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import Avatar from "./Avatar";

describe("Avatar", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render(imageUrl?: string, version?: string, name = "Alex Morgan", className?: string) {
    await act(async () => root.render(<Avatar name={name} imageUrl={imageUrl} version={version} className={className} />));
  }

  it("uses initials for absent images and retains existing avatar styling", async () => {
    await render(undefined, undefined, " Jordan Patel ", "avatar--small");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".avatar.avatar--small")?.textContent).toBe("J");
    expect(container.querySelector(".avatar")?.getAttribute("aria-hidden")).toBe("true");
    await render("   ", undefined, " ");
    expect(container.textContent).toBe("?");
  });

  it("renders a decorative photo with an encoded version", async () => {
    await render("/api/v1/users/alex/avatar/", "2026-10-01T01:02:03+00:00");
    const image = container.querySelector("img")!;
    expect(image.getAttribute("src")).toBe("/api/v1/users/alex/avatar/?v=2026-10-01T01%3A02%3A03%2B00%3A00");
    expect(image.alt).toBe("");
    expect(image.getAttribute("loading")).toBe("lazy");
  });

  it("preserves existing query parameters and fragments without duplicate version keys", async () => {
    await render("/avatar/?size=large&v=old#photo", "fresh");
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/avatar/?size=large&v=fresh#photo");
  });

  it("keeps an unversioned legacy URL unchanged", async () => {
    await render("https://example.com/photo.png?size=large#photo");
    expect(container.querySelector("img")?.getAttribute("src")).toBe("https://example.com/photo.png?size=large#photo");
  });

  it("falls back to initials when the photo fails without repeatedly requesting the broken source", async () => {
    await render("/avatar/");
    await act(async () => container.querySelector("img")!.dispatchEvent(new Event("error")));
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("A");
    await render("/avatar/", undefined, "Alex Morgan", "avatar--small");
    expect(container.querySelector("img")).toBeNull();
  });

  it("retries a replaced photo version and a different URL after a prior failure", async () => {
    await render("/avatar/", "one");
    await act(async () => container.querySelector("img")!.dispatchEvent(new Event("error")));
    await render("/avatar/", "two");
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/avatar/?v=two");
    await act(async () => container.querySelector("img")!.dispatchEvent(new Event("error")));
    await render("/new-avatar/", "two");
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/new-avatar/?v=two");
  });
});
