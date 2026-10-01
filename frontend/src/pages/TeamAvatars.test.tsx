import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { membershipApi } from "../api/resources";
import type { Membership, Page, Project } from "../api/types";
import ProjectOverviewPage from "./ProjectOverviewPage";

vi.mock("../api/resources", () => ({
  projectApi: { get: vi.fn(), update: vi.fn(), archive: vi.fn() },
  membershipApi: { list: vi.fn(), updateRole: vi.fn(), remove: vi.fn(), transferOwnership: vi.fn() },
  invitationApi: { listForProject: vi.fn(), create: vi.fn(), cancel: vi.fn() },
}));

const project: Project = {
  id: "project-team", name: "Study group", description: "Shared project", due_at: null,
  created_by: { id: "alex", display_name: "Alex Morgan" }, created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z", archived_at: null, current_user_role: "member", member_count: 3,
};
const members: Page<Membership> = { count: 3, next: null, previous: null, results: [
  { id: "membership-alex", project: project.id, user: { id: "alex", display_name: "Alex Morgan", avatar_image_url: "/api/v1/users/alex/avatar/", avatar_url: "https://example.com/old.png", avatar_version: "first" }, role: "owner", joined_at: project.created_at, removed_at: null },
  { id: "membership-sam", project: project.id, user: { id: "sam", display_name: "Sam Lee", avatar_image_url: "", avatar_url: "https://example.com/sam.png", avatar_version: "unused" }, role: "facilitator", joined_at: project.created_at, removed_at: null },
  { id: "membership-jordan", project: project.id, user: { id: "jordan", display_name: "Jordan Patel" }, role: "member", joined_at: project.created_at, removed_at: null },
] };

describe("Team member avatars", () => {
  let container: HTMLDivElement;
  let root: Root;
  let client: QueryClient;

  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(["project", project.id], project);
    client.setQueryData(["memberships", project.id], members);
    client.setQueryData(["invitations", project.id], { count: 0, next: null, previous: null, results: [] });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
  });

  async function render() {
    await act(async () => root.render(<QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/app/projects/${project.id}/`]}><Routes>
        <Route path="/app/projects/:projectId/" element={<ProjectOverviewPage />} />
      </Routes></MemoryRouter>
    </QueryClientProvider>));
  }

  function teamRows() { return [...container.querySelectorAll<HTMLElement>('.panel[aria-labelledby="members-heading"] .data-row')]; }

  it("shows uploaded photos first, legacy photos second and initials for older responses", async () => {
    await render();
    const rows = teamRows();
    expect(rows).toHaveLength(3);
    expect(rows[0]!.querySelector("img")?.getAttribute("src")).toBe("/api/v1/users/alex/avatar/?v=first");
    expect(rows[1]!.querySelector("img")?.getAttribute("src")).toBe("https://example.com/sam.png");
    expect(rows[2]!.querySelector(".avatar")?.textContent).toBe("J");
    expect(rows.map((row) => row.querySelector(".badge")?.textContent)).toEqual(["owner", "facilitator", "member"]);
    expect(container.querySelector('[id="role-membership-jordan"]')).toBeNull();
    expect(membershipApi.list).not.toHaveBeenCalled();
  });

  it("updates an existing team row after its membership cache receives a new avatar version", async () => {
    await render();
    const oldImage = teamRows()[0]!.querySelector("img")!;
    await act(async () => oldImage.dispatchEvent(new Event("error")));
    expect(teamRows()[0]!.querySelector(".avatar")?.textContent).toBe("A");
    const replacement = { ...members, results: members.results.map((member) => member.user.id === "alex"
      ? { ...member, user: { ...member.user, avatar_version: "second" } } : member) };
    await act(async () => {
      client.setQueryData(["memberships", project.id], replacement);
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(teamRows()[0]!.querySelector("img")?.getAttribute("src")).toBe("/api/v1/users/alex/avatar/?v=second");
  });

  it("preserves owner-only role controls alongside the new photos", async () => {
    client.setQueryData(["project", project.id], { ...project, current_user_role: "owner" });
    await render();
    expect(container.querySelector<HTMLSelectElement>('[id="role-membership-sam"]')?.value).toBe("facilitator");
    expect(container.querySelector<HTMLSelectElement>('[id="role-membership-jordan"]')?.value).toBe("member");
    expect(container.querySelector('[id="role-membership-alex"]')).toBeNull();
    expect(container.textContent).toContain("Make owner");
    expect(container.textContent).toContain("Remove");
  });
});
