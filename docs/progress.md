# StudyCrew assignment progress

## 16 September 2026

| Phase | Status | Evidence |
|---|---|---|
| Assignment 2 release candidate | Repository-ready | 275 Django tests, 96.3% branch coverage, 18 frontend tests, zero-warning OpenAPI validation, TypeScript and 84-module production build |
| Final workflow hardening | Implemented | Delivered invitation rollback, archive-wide read-only guards and discoverable task history, canonical task URLs, complete paginated client reads, strict API write contracts, field feedback and lossless evidence exports |
| Interface acceptance | Verified locally | Fifteen public, account, workspace and moderator surfaces inspected at 360, 768 and 1440 px; no page-level horizontal scroll, duplicate IDs, unnamed buttons or unlabelled controls; destructive actions use contextual inline confirmation |
| Architecture boundaries | Executable | Dependency guard rejects domain-to-HTTP imports, cross-domain model imports, external HTTP outside `integrations/`, frontend fetches outside the shared client and route strings outside the API module |
| Assignment 3 handover | Repository-ready | Fail-closed production check, least-privilege PostgreSQL script, Nginx/uWSGI/systemd assets, deployment verifier, honest live-evidence checklist and report guide |
| AWS/Canvas/GitHub evidence | Team action required | Final EC2 deployment, live certificate/reboot/firewall/psql/concurrency captures, official Canvas templates, video and course-organisation history |

## 13 September 2026

| Phase | Status | Evidence |
|---|---|---|
| Assignment 2 backend | Implemented | Modular Django apps, 18 domain/security tables, transactional services and versioned REST API |
| Assignment 2 frontend | Implemented | Responsive React/TypeScript workspace, custom control centre and AJAX workflows |
| Authentication/security | Implemented and tested | Argon2, password complexity, persistent lockout, email OTP MFA, CSRF, object permissions and safe errors |
| Automated QA | Passing locally | Django suite, branch coverage gate, OpenAPI validation, TypeScript, Vitest and Vite build |
| Assignment 3 configuration | Prepared | Nginx/uWSGI/systemd/PostgreSQL hardening and concurrent HTTPS verifier |
| Assignment 3 live evidence | Team action required | Real EC2 hostname, TLS certificate, firewall, reboot, psql and load-test captures |

The repository never claims learner-lab actions that have not been performed on
the team's actual AWS account.

## 20 August 2026

| Phase | Status | Evidence |
|---|---|---|
| Concept and scope | Complete | StudyCrew product definition, users, scope boundary and MVP rule |
| Functional requirements | Complete | 18 measurable IEEE 830-style requirements; 16 authenticated functions |
| Physical data model | Complete | PostgreSQL 16 schema, 13 tables, constraints, indexes and Crow's Foot ERDs |
| Interface design | Complete | 11 grayscale generic-view wireframes with embedded requirement tags |
| Traceability | Complete | 18/18 requirements linked to tables, views and MVP status |
| Final report | Complete | 27-page DOCX and PDF, visually inspected page by page |
| Milestone package | Complete | MVP proposal, 6-slide pitch, 5-minute script and contract working draft |
| Automated QA | Complete | PDF page checks, PPTX overflow test and repository acceptance audit |

## Human actions still required

1. Replace all group-member placeholders, transfer the agreed contract terms to the official Canvas template and obtain every member's signature.
2. Present the proposed MVP to the tutor and record the approval or required changes.
3. Assign Speaker A/B/C/D, rehearse twice, and confirm a duration between 4:50 and 5:00.
4. Confirm the final Canvas naming convention and upload only the required PDFs before each deadline.

These actions are deliberately not marked complete because they require the group or tutor, not repository automation.
