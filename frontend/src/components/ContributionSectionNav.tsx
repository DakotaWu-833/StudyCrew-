export interface ContributionSection {
  id: string;
  label: string;
}

export default function ContributionSectionNav({
  items,
  activeSection,
}: {
  items: ContributionSection[];
  activeSection: string;
}) {
  if (!items.length) return null;

  return (
    <aside className="contribution-section-nav" aria-label="Contribution page navigation">
      <nav aria-label="Jump to section">
        <ol className="contribution-section-nav__list">
          {items.map(({ id, label }) => (
            <li key={id}>
              <a
                href={`#${id}`}
                aria-label={label}
                aria-current={activeSection === id ? "location" : undefined}
              >
                <span className="contribution-section-nav__mark" aria-hidden="true" />
                <span className="contribution-section-nav__label">{label}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>
    </aside>
  );
}
