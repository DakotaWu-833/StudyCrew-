import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ContributionSectionNav from "./ContributionSectionNav";

describe("ContributionSectionNav", () => {
  it("links to each page section and marks the current position accessibly", () => {
    const markup = renderToStaticMarkup(
      <ContributionSectionNav
        activeSection="timeline-heading"
        items={[
          { id: "contribution-dashboard-heading", label: "Overview" },
          { id: "timeline-heading", label: "Activity timeline" },
        ]}
      />,
    );

    expect(markup).toContain('aria-label="Contribution page navigation"');
    expect(markup).toContain('href="#contribution-dashboard-heading"');
    expect(markup).toContain('href="#timeline-heading"');
    expect(markup).toContain('aria-current="location"');
    expect(markup).toContain("Activity timeline");
  });

  it("does not render an empty rail before sections are available", () => {
    expect(renderToStaticMarkup(<ContributionSectionNav items={[]} activeSection="" />)).toBe("");
  });
});
