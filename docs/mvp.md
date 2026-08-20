# StudyCrew Proposed Minimum Viable Product

## Product statement

StudyCrew is a responsive web application that helps university project teams
plan work, coordinate meetings and review factual contribution evidence in one
private project space. It addresses two recurring team risks: important work
becoming visible too late, and contribution discussions relying on memory rather
than traceable activity.

## MVP features

1. Secure account registration, sign-in and sign-out (`FR-AUTH-01/02`).
2. Personal profile and time-zone preference (`FR-PROF-01`).
3. Project creation and invitation-based membership (`FR-PROJ-01/02`).
4. Task create/edit/archive, multi-member assignment and status workflow
   (`FR-TASK-01/02/03`).
5. Sanitised task comments with ownership and moderation rules (`FR-COLL-01`).
6. Meeting scheduling, cancellation and per-member RSVP (`FR-MEET-01/02`).
7. Immutable activity evidence and per-member contribution insights
   (`FR-CONTR-01/02`).
8. In-app assignment, mention, meeting and invitation notifications
   (`FR-NOTIF-01`).
9. Server-side project membership and role enforcement on all protected data
   (`FR-SEC-01`).

Search/filter (`FR-SEARCH-01`) and PDF/CSV export (`FR-EXPORT-01`) are deliberately
outside the MVP. They remain fully designed, but will be implemented only after
the core quality gates pass.

## Completion test

The MVP is complete when every included requirement passes its documented
acceptance condition, the automated access-control matrix passes for visitor,
non-member, member and owner roles, all seeded desktop/mobile user journeys can
be completed, and there are no unresolved severity-1 defects.

## Feasibility

The proposed implementation uses a React client, Node.js/Express API and
PostgreSQL database. A small team can deliver the MVP incrementally because each
feature maps to explicit tables and acceptance tests; contribution insights are
derived from the same activity events already recorded by normal collaboration.

