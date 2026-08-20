# ELEC3609/9609 Assignment 1 - StudyCrew

StudyCrew is a web application concept for university project teams. It combines
task planning, meeting coordination and evidence-based contribution tracking so
teams can identify delivery risk early and discuss workload using transparent
activity records.

## Repository structure

- `docs/requirements.md` - IEEE 830-style functional requirements and MVP scope.
- `database/schema.sql` - PostgreSQL physical data model with keys and constraints.
- `design/` - ERD and wireframe source assets.
- `scripts/` - reproducible artifact builders and quality checks.
- `deliverables/` - submission-ready DOCX, PPTX and PDF files.

## Submission checklist

- [x] At least five authenticated functions (16 are specified).
- [x] At least six database tables (13 are specified).
- [x] One-to-one, one-to-many and many-to-many relationships.
- [x] Crow's Foot ERD and complete data dictionary.
- [x] Wireframes for every generic view and all functional requirements.
- [x] Five-minute milestone pitch with Gantt chart and technology dependencies.
- [x] Final visual and traceability audit.

Run the reproducible acceptance audit with:

```powershell
python scripts/validate_submission.py
```

The group contract remains unsigned until each member enters their details and
signs the official Canvas template. Tutor approval of the proposed MVP is also
a required human milestone; neither action should be represented as complete in
the repository before it occurs.
