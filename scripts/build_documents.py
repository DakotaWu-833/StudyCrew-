from __future__ import annotations

import csv
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables"
VISUALS = ROOT / "design" / "generated"
OUT.mkdir(parents=True, exist_ok=True)

INK = "172A3A"
BLUE = "2E74B5"
PALE = "E8EEF5"
LIGHT = "F4F6F9"
GRAY = "5F6B76"
WHITE = "FFFFFF"
BLACK = "000000"


def set_font(run, name="Calibri", size=None, bold=None, color=None, italic=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_row_cant_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    cant_split.set(qn("w:val"), "true")
    tr_pr.append(cant_split)


def shade_cell(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for key, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{key}"))
        if node is None:
            node = OxmlElement(f"w:{key}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths_dxa, indent=120):
    total = sum(widths_dxa)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent))
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            width = widths_dxa[min(index, len(widths_dxa) - 1)]
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_page_field(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("PAGE ")
    set_font(run, size=9, color=GRAY)
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char1, instr, fld_char2])


def configure_document(doc: Document, preset="narrative"):
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.85)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal.font.size = Pt(10.5 if preset == "compact" else 11)
    normal.paragraph_format.space_after = Pt(6 if preset == "compact" else 8)
    normal.paragraph_format.line_spacing = 1.25 if preset == "compact" else 1.333
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    for name, size, color, before, after in (
        ("Title", 28, INK, 0, 12),
        ("Subtitle", 13, GRAY, 0, 18),
        ("Heading 1", 16, BLUE, 18, 10),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, INK, 8, 4),
    ):
        style = styles[name]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = name != "Subtitle"
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for sec in doc.sections:
        header = sec.header
        hp = header.paragraphs[0]
        hp.text = "STUDYCREW  |  ELEC3609/9609 ASSIGNMENT 1"
        set_font(hp.runs[0], size=8.5, bold=True, color=GRAY)
        hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        add_page_field(sec.footer.paragraphs[0])


def add_title_block(doc, title, subtitle, label, metadata):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(80)
    p.paragraph_format.space_after = Pt(12)
    r = p.add_run(label.upper())
    set_font(r, size=10, bold=True, color=BLUE)
    p = doc.add_paragraph(style="Title")
    p.add_run(title)
    p = doc.add_paragraph(style="Subtitle")
    p.add_run(subtitle)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(130)
    p.paragraph_format.space_after = Pt(12)
    r = p.add_run("A design for visible work, earlier intervention and fairer team conversations.")
    set_font(r, size=15, bold=True, color=INK)
    table = doc.add_table(rows=len(metadata), cols=2)
    table.style = "Table Grid"
    for row, (key, value) in zip(table.rows, metadata):
        row.cells[0].text = key
        row.cells[1].text = value
        shade_cell(row.cells[0], PALE)
        set_font(row.cells[0].paragraphs[0].runs[0], size=9, bold=True, color=INK)
        set_font(row.cells[1].paragraphs[0].runs[0], size=9.5)
    set_table_geometry(table, [2700, 6660])
    doc.add_page_break()


def add_callout(doc, title, body):
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    set_row_cant_split(table.rows[0])
    shade_cell(cell, LIGHT)
    p = cell.paragraphs[0]
    r = p.add_run(title + "  ")
    set_font(r, bold=True, color=INK)
    r = p.add_run(body)
    set_font(r)
    set_table_geometry(table, [9360])
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_text_table(doc, headers, rows, widths, font_size=8.5, header_fill=PALE):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, text in enumerate(headers):
        table.rows[0].cells[i].text = text
        shade_cell(table.rows[0].cells[i], header_fill)
        for run in table.rows[0].cells[i].paragraphs[0].runs:
            set_font(run, size=font_size, bold=True, color=INK)
    set_repeat_table_header(table.rows[0])
    for values in rows:
        cells = table.add_row().cells
        for i, text in enumerate(values):
            cells[i].text = str(text)
            for p in cells[i].paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.05
                for run in p.runs:
                    set_font(run, size=font_size)
    set_table_geometry(table, widths)
    return table


def parse_requirements():
    text = (ROOT / "docs" / "requirements.md").read_text(encoding="utf-8")
    matches = list(re.finditer(r"^### (FR-[A-Z]+-\d+) - (.+)$", text, re.MULTILINE))
    requirements = []
    for index, match in enumerate(matches):
        chunk = text[match.end(): matches[index + 1].start() if index + 1 < len(matches) else text.find("## 4.", match.end())]
        shall_match = re.search(r"\*\*Requirement\.\*\*\s*(.+?)(?=\n\n- \*\*)", chunk, re.DOTALL)
        details = {}
        for detail in re.finditer(r"- \*\*(.+?):\*\*\s*(.+?)(?=\n- \*\*|\n\n|\Z)", chunk, re.DOTALL):
            details[detail.group(1)] = re.sub(r"\s+", " ", detail.group(2)).strip()
        requirements.append({
            "id": match.group(1),
            "title": match.group(2),
            "shall": re.sub(r"\s+", " ", shall_match.group(1)).strip(),
            "details": details,
        })
    return requirements


def load_traceability():
    with (ROOT / "docs" / "traceability.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def add_section_without_blank_page(doc, start_type=WD_SECTION.NEW_PAGE):
    previous_paragraph = doc.paragraphs[-1]._p
    section = doc.add_section(start_type)
    break_paragraph = doc.paragraphs[-1]._p
    sect_pr = break_paragraph.pPr.sectPr
    previous_paragraph.get_or_add_pPr().append(sect_pr)
    break_paragraph.getparent().remove(break_paragraph)
    return section


TABLES = [
    ("users", "Account identity and credential state", "user_id", "profiles, projects, memberships and authored records"),
    ("profiles", "One profile per account", "user_id (PK/FK)", "Exactly one-to-one with users"),
    ("projects", "Private team workspace", "project_id", "Created by user; owns memberships, tasks, meetings and events"),
    ("project_members", "User-project junction and role", "project_id + user_id", "Many-to-many users/projects; one active owner per project"),
    ("project_invitations", "Time-limited invitation lifecycle", "invitation_id", "Belongs to project; invited by user; unique pending email"),
    ("tasks", "Project work item and workflow state", "task_id", "Belongs to project; created by user; owns assignees/comments"),
    ("task_assignees", "Task-user assignment junction", "task_id + user_id", "Many-to-many tasks/users; no duplicate assignment"),
    ("task_comments", "Sanitised task discussion", "comment_id", "Belongs to task; authored/moderated by users"),
    ("meetings", "Scheduled or cancelled project meeting", "meeting_id", "Belongs to project; organised by user; owns attendance"),
    ("meeting_attendees", "One RSVP per meeting/member", "meeting_id + user_id", "Many-to-many meetings/users"),
    ("activity_events", "Append-only contribution evidence", "event_id", "Belongs to project/actor; optional single source target"),
    ("notifications", "Recipient-specific in-app alert", "notification_id", "Unique recipient/source-event pair"),
    ("export_jobs", "Asynchronous evidence export", "export_job_id", "Belongs to project/requester; bounded range and expiry"),
]


WIREFRAMES = [
    ("WF-01", "Authentication", "wf-01-auth.png"),
    ("WF-02", "Project dashboard", "wf-02-dashboard.png"),
    ("WF-03", "Project overview", "wf-03-project-overview.png"),
    ("WF-04", "Task board", "wf-04-task-board.png"),
    ("WF-05", "Task detail and discussion", "wf-05-task-detail.png"),
    ("WF-06", "Members and invitations", "wf-06-members.png"),
    ("WF-07", "Meetings and RSVP", "wf-07-meetings.png"),
    ("WF-08", "Contribution evidence", "wf-08-contributions.png"),
    ("WF-09", "Notifications", "wf-09-notifications.png"),
    ("WF-10", "Profile", "wf-10-profile.png"),
    ("WF-11", "Evidence export", "wf-11-export.png"),
]


def add_erd_spread(doc, image_stem, figure_number):
    for part, label in (("a", "left/centre"), ("b", "centre/right")):
        doc.add_page_break()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(VISUALS / f"{image_stem}-{part}.png"), width=Inches(6.35))
        cap = doc.add_paragraph(
            f"Figure {figure_number}{part.upper()}. Physical ERD {figure_number}/3 ({label} view) in Crow's Foot notation. "
            "The deliberate overlap preserves relationship context; the complete landscape diagram is included in the repository."
        )
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_before = Pt(2)
        for run in cap.runs:
            set_font(run, size=9, italic=True, color=GRAY)


def build_report():
    requirements = parse_requirements()
    trace = load_traceability()
    trace_by_id = {row["Requirement"]: row for row in trace}
    doc = Document()
    configure_document(doc, "narrative")
    add_title_block(
        doc,
        "StudyCrew System & Database Design",
        "Functional requirements, physical data model and complete interface wireframes",
        "ELEC3609/9609 · Assignment 1",
        [("Team", "ELEC3609-Fri13-16-G02"), ("Version", "1.0 · 20 August 2026"), ("Submission", "Final system design report"), ("Product", "StudyCrew")],
    )

    doc.add_heading("Document control", level=1)
    add_text_table(doc, ["Version", "Date", "Status", "Scope"], [["0.1", "20 Aug 2026", "Draft", "Concept and requirement baseline"], ["0.7", "20 Aug 2026", "Reviewed", "ERD, wireframes and traceability"], ["1.0", "20 Aug 2026", "Submission candidate", "Integrated report"]], [1200, 1800, 2100, 4260], 8.5)
    doc.add_heading("Contents", level=1)
    add_text_table(doc, ["Section", "Evidence delivered"], [
        ["1. Product definition", "Problem, users, value and design boundary"],
        ["2. Functional requirements", "18 measurable IEEE 830-style requirements"],
        ["3. Data model", "13-table 3NF model, Crow's Foot ERDs and constraints"],
        ["4. Wireframes", "11 generic views covering every requirement"],
        ["5. Traceability", "Requirement-to-table-to-view-to-MVP matrix"],
        ["6. Quality and feasibility", "Normalisation, security, accessibility and risks"],
    ], [2500, 6860], 9)

    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph("StudyCrew gives university project teams one private place to plan tasks, coordinate meetings and review factual contribution evidence. Its differentiator is not another task board: every meaningful collaboration action produces an immutable, inspectable event. The resulting dashboard supports earlier workload conversations without converting activity into an automated grade.")
    add_callout(doc, "Design thesis", "Make work visible early enough to act, while keeping contribution evidence transparent, contextual and non-judgemental.")

    doc.add_heading("1. Product definition", level=1)
    doc.add_heading("1.1 Problem and opportunity", level=2)
    doc.add_paragraph("Small student teams often split coordination across chat, calendars and task lists. Status becomes stale, meeting attendance is hard to reconstruct and contribution concerns surface close to submission. StudyCrew unifies planning and evidence so the team can see blocked work, upcoming commitments and activity history before delivery risk becomes critical.")
    doc.add_heading("1.2 Primary users and outcomes", level=2)
    add_text_table(doc, ["Actor", "Need", "Successful outcome"], [
        ["Project member", "Know what to do and where discussion belongs", "Find assigned work, update status and collaborate without losing context"],
        ["Project owner", "Coordinate access and respond to delivery risk", "Invite members, manage roles and identify blocked or overdue work"],
        ["Whole team", "Discuss contribution using shared facts", "Reconcile activity totals with underlying events without a black-box score"],
    ], [1800, 3500, 4060], 8.5)
    doc.add_heading("1.3 Scope boundary", level=2)
    doc.add_paragraph("In scope: authenticated project collaboration, task workflow, comments, meetings, RSVP, activity evidence, in-app notifications, search/filter and evidence export. Out of scope: grading, sentiment analysis, peer scoring, LMS synchronisation, external email delivery, real-time chat and native mobile applications.")
    doc.add_heading("1.4 Assumptions", level=2)
    add_text_table(doc, ["Assumption", "Design response"], [
        ["A user may belong to multiple projects", "Membership is a junction table; every project query is membership-scoped"],
        ["One active owner must remain", "A partial unique index permits one active owner and application logic prevents sole-owner removal"],
        ["Evidence must survive ordinary edits", "Source records use soft retention where needed and activity events are append-only"],
        ["Users may be in different time zones", "All instants use timestamptz/UTC and profiles store an IANA time zone"],
    ], [3500, 5860], 8.5)

    doc.add_heading("2. Functional requirements", level=1)
    doc.add_paragraph("The specification follows the assignment's IEEE 830-1998 Section 5.3.2 expectation. Each requirement is uniquely identified, uses mandatory shall language and defines inputs, processing, outputs, failure behaviour and a measurable acceptance condition. Sixteen of the eighteen functions are available only to authenticated users.")
    add_callout(doc, "MVP rule", "The proposed MVP contains 15 requirements. FR-SEARCH-01 and FR-EXPORT-01 are designed extensions and are implemented only after the core quality gates pass.")
    for req in requirements:
        doc.add_heading(f"{req['id']} · {req['title']}", level=2)
        rows = [["Shall statement", req["shall"]]]
        for label in ("Input/trigger", "Processing", "Success output", "Failure output", "Acceptance"):
            rows.append([label, req["details"].get(label, "")])
        trace_row = trace_by_id[req["id"]]
        rows.append(["Trace", f"Tables: {trace_row['Primary tables']} | Views: {trace_row['Wireframe views']} | MVP: {trace_row['MVP']}"])
        add_text_table(doc, ["Element", "Specification"], rows, [1900, 7460], 8.2)

    doc.add_heading("3. Data model", level=1)
    doc.add_heading("3.1 Modelling decisions", level=2)
    doc.add_paragraph("The physical model targets PostgreSQL 16. UUID keys are used for externally visible entities; bigint identity keys support high-volume immutable events and notifications. All instants use timestamptz. Enumerated states are represented by constrained varchar values so the allowed domain is explicit in the schema and ERD.")
    add_text_table(doc, ["Required association", "Implementation", "Integrity evidence"], [
        ["One-to-one", "users to profiles", "profiles.user_id is both PK and FK; a profile cannot exist without one user"],
        ["One-to-many", "projects to tasks", "tasks.project_id is NOT NULL; each task belongs to exactly one project"],
        ["Many-to-many", "users to projects", "project_members has composite PK (project_id, user_id)"],
        ["Many-to-many", "users to tasks", "task_assignees has composite PK (task_id, user_id)"],
        ["Many-to-many", "users to meetings", "meeting_attendees has composite PK (meeting_id, user_id)"],
    ], [1700, 3300, 4360], 8.3)

    doc.add_heading("3.2 Table catalogue", level=2)
    add_text_table(doc, ["Table", "Purpose", "Primary key", "Principal relationships / constraints"], TABLES, [1500, 2600, 1900, 3360], 7.8)
    doc.add_heading("3.3 Normalisation", level=2)
    doc.add_paragraph("The schema satisfies third normal form. Repeating memberships, assignments and attendance are isolated in junction tables; non-key attributes describe only their table key; profile data is separated from credentials; derived contribution totals are calculated from events rather than stored; and notification/export lifecycle state is isolated from source collaboration records. JSONB is restricted to non-authoritative event metadata, while all reportable identities and relationships remain typed foreign keys.")

    for index, stem in enumerate(("erd-1-identity-projects", "erd-2-tasks-collaboration", "erd-3-meetings-evidence"), start=1):
        add_erd_spread(doc, stem, index)
    doc.add_page_break()

    doc.add_heading("3.4 Integrity and performance controls", level=2)
    add_text_table(doc, ["Concern", "Control"], [
        ["Duplicate identity", "Lowercase email check plus unique users.email"],
        ["Multiple active owners", "Partial unique index on active owner membership"],
        ["Duplicate invitations / notifications", "Partial and composite unique indexes"],
        ["Invalid workflow state", "CHECK domains for task, meeting, invitation, export and notification state"],
        ["Inconsistent completion", "Task completion timestamp constraint tied to done status"],
        ["Slow board and evidence queries", "Composite indexes on project/status/priority and project/occurred_at"],
        ["Evidence tampering", "Append-only activity policy; application roles receive no UPDATE/DELETE grant"],
    ], [2800, 6560], 8.5)

    doc.add_heading("4. Wireframes", level=1)
    doc.add_paragraph("The wireframes intentionally omit colour and theming. They define information hierarchy, user controls, error/empty-state intent and cross-view flow. Requirement tags embedded in each frame make coverage directly inspectable.")
    for index, (wf_id, title, filename) in enumerate(WIREFRAMES):
        doc.add_heading(f"{wf_id} · {title}", level=2)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(1)
        p.add_run().add_picture(str(VISUALS / filename), width=Inches(5.7))
        rows = [r for r in trace if wf_id in r["Wireframe views"] or (wf_id != "WF-01" and r["Wireframe views"] == "WF-02 to WF-11")]
        coverage = ", ".join(row["Requirement"] for row in rows)
        cap = doc.add_paragraph(f"Figure {index + 4}. {wf_id} {title}. Coverage: {coverage}.")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in cap.runs:
            set_font(run, size=8.5, italic=True, color=GRAY)
        if index % 2 == 1 and index != len(WIREFRAMES) - 1:
            doc.add_page_break()

    doc.add_heading("4.1 End-to-end user flows", level=2)
    add_text_table(doc, ["Flow", "Views", "Completion evidence"], [
        ["Start a team", "WF-01 → WF-02 → WF-06 → WF-03", "Owner account, project and accepted membership exist"],
        ["Deliver a task", "WF-04 → WF-05 → WF-04", "Task assigned, discussed and moved to done with event record"],
        ["Coordinate a meeting", "WF-07 → WF-09", "Valid UTC meeting, one RSVP per member and change notification"],
        ["Review contribution", "WF-08 → event drill-down → WF-11", "Totals reconcile to immutable events and authorised export"],
    ], [2300, 3000, 4060], 8.5)

    doc.add_heading("5. Traceability matrix", level=1)
    add_text_table(doc, ["Requirement", "Primary tables", "Wireframes", "MVP"], [[r["Requirement"], r["Primary tables"], r["Wireframe views"], r["MVP"]] for r in trace], [1500, 4200, 2300, 1360], 7.8)
    doc.add_paragraph("Coverage audit: 18/18 requirements map to at least one table and one wireframe. All 13 tables appear in the ERDs. The 15 MVP requirements map to concrete acceptance conditions; the two post-MVP features remain designed and traceable.")

    doc.add_heading("6. Quality, feasibility and risk", level=1)
    doc.add_heading("6.1 Security and privacy", level=2)
    doc.add_paragraph("Server-side authorisation derives identity from the session and checks current membership before every project-scoped query or mutation. Password hashes, invitation token hashes and account emails never enter activity metadata or exports. Soft removal immediately revokes project access. Exports expire after 24 hours and each download rechecks membership.")
    doc.add_heading("6.2 Accessibility and responsive behaviour", level=2)
    doc.add_paragraph("Interactive controls use visible labels and keyboard focus; task status changes are announced in an accessible live region; charts have equivalent tables; errors identify fields in text; and colour is never the sole state indicator. At narrow widths, the sidebar becomes a menu, board columns scroll horizontally with labelled regions and forms collapse to one column without changing function.")
    doc.add_heading("6.3 Feasibility", level=2)
    add_text_table(doc, ["Layer", "Proposed dependency", "Reason"], [
        ["Client", "React + accessible component primitives", "Responsive views and predictable state-driven interactions"],
        ["API", "Node.js + Express", "Small-team familiarity and testable REST boundary"],
        ["Data", "PostgreSQL + Prisma", "Relational integrity, transactions and explicit migrations"],
        ["Testing", "Vitest + Playwright", "Unit, integration, access-control and end-to-end journeys"],
        ["Delivery", "GitHub Actions + Docker", "Repeatable checks and environment parity"],
    ], [1600, 3300, 4460], 8.5)
    doc.add_heading("6.4 Principal risks", level=2)
    add_text_table(doc, ["Risk", "Likelihood / impact", "Mitigation and trigger"], [
        ["Activity counts interpreted as grades", "Medium / High", "No score; show definitions and event drill-down; revise language if users infer quality"],
        ["Scope expansion", "High / Medium", "Freeze approved MVP; search/export remain post-MVP until quality gates pass"],
        ["Authorisation leak", "Low / High", "Central policy middleware and route-by-role matrix in CI"],
        ["Late integration", "Medium / High", "Vertical slices from week 7; seeded journeys pass at each milestone"],
    ], [2600, 1800, 4960], 8.2)

    doc.add_heading("References", level=1)
    doc.add_paragraph("[1] IEEE Computer Society, IEEE Std 830-1998, IEEE Recommended Practice for Software Requirements Specifications, 1998. Superseded standard; used because the assignment explicitly requires Section 5.3.2.")
    doc.add_paragraph("[2] ELEC3609/9609 Group Project, Assignment 1: System & Database Design, 2026.")
    doc.add_paragraph("Schema source: database/schema.sql. Requirement source: docs/requirements.md. Traceability source: docs/traceability.csv.")

    path = OUT / "StudyCrew_System_Design_Report.docx"
    doc.save(path)
    return path


def build_mvp():
    doc = Document()
    configure_document(doc, "compact")
    add_title_block(doc, "StudyCrew Proposed MVP", "A realistic, assessable web application scope for tutor approval", "ELEC3609/9609 milestone", [("Team", "ELEC3609-Fri13-16-G02"), ("Decision requested", "Approve / approve with changes / revise"), ("Version", "1.0 · 20 August 2026")])
    doc.add_heading("Product in one paragraph", level=1)
    doc.add_paragraph("StudyCrew is a responsive web application that helps university project teams plan work, coordinate meetings and review factual contribution evidence in one private project space. It addresses two recurring team risks: important work becoming visible too late, and contribution discussions relying on memory rather than traceable activity.")
    add_callout(doc, "MVP promise", "A team can create a protected workspace, organise tasks and meetings, then reconcile contribution activity with the source events that produced each total.")
    doc.add_heading("Core feature set", level=1)
    features = [
        ["1", "Account and profile", "FR-AUTH-01/02, FR-PROF-01", "Register, authenticate, sign out and maintain time-zone-aware identity"],
        ["2", "Private projects", "FR-PROJ-01/02", "Create a project and join through an expiring invitation"],
        ["3", "Task collaboration", "FR-TASK-01/02/03, FR-COLL-01", "Plan, assign, progress and discuss retained work"],
        ["4", "Meeting coordination", "FR-MEET-01/02", "Schedule/cancel meetings and collect one RSVP per member"],
        ["5", "Contribution evidence", "FR-CONTR-01/02", "Append immutable events and reconcile per-member summaries"],
        ["6", "In-app alerts", "FR-NOTIF-01", "Notify relevant users about invitations, assignments, mentions and meetings"],
        ["7", "Access control", "FR-SEC-01", "Enforce membership and role checks on every protected route"],
    ]
    add_text_table(doc, ["#", "Capability", "Requirements", "Demonstrable outcome"], features, [600, 1900, 2500, 4360], 8.3)
    doc.add_heading("Deliberate exclusions", level=1)
    doc.add_paragraph("Search/filter (FR-SEARCH-01) and PDF/CSV export (FR-EXPORT-01) are fully designed but excluded from the approved baseline. They become stretch work only after all core acceptance and security checks pass. Grading, contribution scoring, LMS integration, email delivery, live chat and native mobile apps are not planned.")
    doc.add_heading("Completion gates", level=1)
    add_text_table(doc, ["Gate", "Pass condition"], [
        ["Functional", "Every included requirement passes its stated acceptance check"],
        ["Security", "Visitor, non-member, member and owner access-control matrix passes"],
        ["Usability", "Seeded desktop and mobile journeys complete without a blocked step"],
        ["Reliability", "No open severity-1 defect; transactions leave no partial project data"],
        ["Evidence", "Contribution totals reconcile exactly with the reference event query"],
    ], [2200, 7160], 9)
    doc.add_heading("Feasibility and implementation order", level=1)
    add_text_table(doc, ["Increment", "Vertical slice"], [
        ["1", "Authentication, profile, project creation and membership boundary"],
        ["2", "Task board, assignment, workflow and comments"],
        ["3", "Meetings, RSVP and notifications"],
        ["4", "Activity feed, contribution dashboard and final hardening"],
    ], [1600, 7760], 9)
    doc.add_heading("Tutor decision", level=1)
    add_text_table(doc, ["Decision", "Comments / required changes"], [["☐ Approved   ☐ Approved with changes   ☐ Revise", ""], ["Tutor / date", ""]], [4300, 5060], 9)
    path = OUT / "StudyCrew_MVP_Proposal.docx"
    doc.save(path)
    return path


def build_contract():
    doc = Document()
    configure_document(doc, "compact")
    add_title_block(doc, "Group Contract Working Draft", "StudyCrew · ELEC3609/9609 Assignment 1", "Not a substitute for the official Canvas template", [("Team", "ELEC3609-Fri13-16-G02"), ("Status", "Complete member details, transfer to Canvas template, then sign"), ("Date", "[DD Month 2026]")])
    add_callout(doc, "Submission warning", "Canvas provides the official contract template. This working draft organises agreed terms but must be transferred to that template and signed by every member before milestone submission.")
    doc.add_heading("1. Team membership and contacts", level=1)
    rows = [[f"Member {i}", "[Full name]", "[SID]", "[University email]", "[Preferred contact]"] for i in range(1, 6)]
    add_text_table(doc, ["Member", "Name", "Student ID", "Email", "Contact"], rows, [1100, 1900, 1600, 2860, 1900], 8)
    doc.add_heading("2. Shared commitments", level=1)
    commitments = [
        ["Attendance", "Attend agreed meetings or notify the team at least 12 hours before absence where possible."],
        ["Communication", "Acknowledge direct team messages within 24 hours on weekdays and identify blockers early."],
        ["Quality", "Submit work for peer review before the internal deadline; respond to review comments constructively."],
        ["Version control", "Use feature branches and reviewed pull requests; do not rewrite shared branch history."],
        ["Academic integrity", "Attribute sources, disclose assistance as required and do not submit unreviewed generated content."],
        ["Respect", "Discuss evidence and deliverables rather than personalities; provide equal opportunity to contribute and present."],
    ]
    add_text_table(doc, ["Area", "Agreement"], commitments, [2000, 7360], 8.5)
    doc.add_heading("3. Roles and responsibilities", level=1)
    add_text_table(doc, ["Role", "Primary responsibilities", "Owner", "Backup"], [
        ["Project coordinator", "Agenda, timeline, risk register and tutor communication", "[Name]", "[Name]"],
        ["Requirements lead", "Requirement quality, acceptance checks and traceability", "[Name]", "[Name]"],
        ["Data lead", "ERD, schema consistency, normalisation and database review", "[Name]", "[Name]"],
        ["UX lead", "User flows, wireframes, accessibility and presentation visuals", "[Name]", "[Name]"],
        ["Quality/release lead", "Document integration, QA, submission package and repository release", "[Name]", "[Name]"],
    ], [1800, 4160, 1700, 1700], 8.2)
    doc.add_heading("4. Working cadence", level=1)
    add_text_table(doc, ["Practice", "Agreement"], [
        ["Regular meeting", "[Day/time/location]; 30-45 minutes; coordinator records decisions and actions"],
        ["Internal deadline", "Each deliverable is review-ready at least 48 hours before the Canvas deadline"],
        ["Task ownership", "Every task has one accountable owner, due date, status and acceptance condition"],
        ["Decision rule", "Seek consensus; if unresolved after documented discussion, simple majority decides; ties escalate to tutor guidance"],
        ["Repository", "Protected main branch; descriptive commits; one reviewer for material changes"],
    ], [2200, 7160], 8.5)
    doc.add_heading("5. Conflict and non-performance process", level=1)
    add_text_table(doc, ["Step", "Action"], [
        ["1. Private check-in", "Two members clarify the missed commitment and agree a recovery action/date."],
        ["2. Team review", "If repeated, the team records evidence, impact and a redistributed plan in meeting notes."],
        ["3. Written agreement", "The affected member confirms the recovery plan and next checkpoint."],
        ["4. Tutor support", "If still unresolved, the group seeks tutor guidance with the documented timeline; the team remains responsible for internal resolution."],
    ], [1600, 7760], 8.5)
    doc.add_heading("6. Signatures", level=1)
    signature_rows = [[f"Member {i}: [Full name]", "Signature: ____________________", "Date: __________"] for i in range(1, 6)]
    add_text_table(doc, ["Member", "Signature", "Date"], signature_rows, [3600, 3700, 2060], 9)
    doc.add_paragraph("By signing, each member confirms team membership, shared responsibilities and the internal resolution process. Changes after signing are subject to the unit's published rules.")
    path = OUT / "StudyCrew_Group_Contract_Working_Draft.docx"
    doc.save(path)
    return path


def build_script():
    doc = Document()
    configure_document(doc, "compact")
    add_title_block(doc, "StudyCrew Milestone Presentation Script", "Five-minute pitch, hand-offs and Q&A preparation", "ELEC3609/9609 · Group 02", [("Target duration", "4:50-5:00"), ("Slides", "6"), ("Presenters", "Assign Speaker A/B/C/D before rehearsal")])
    add_callout(doc, "Delivery rule", "Use the script to rehearse, not to read. Each presenter should memorise their opening and closing sentence, understand every slide and be ready for Q&A.")
    script_rows = [
        ["1 · 0:00-0:25", "Speaker A", "StudyCrew makes group work visible before it becomes a problem. It gives student teams one place to coordinate tasks and meetings, then backs contribution conversations with transparent activity evidence."],
        ["2 · 0:25-1:05", "Speaker A", "Today, work is often split across chat, calendars and task lists. Status becomes stale, blockers surface late, and contribution discussions depend on memory. Teams need coordination and evidence together, without a black-box score."],
        ["3 · 1:05-2:00", "Speaker B", "StudyCrew follows a simple loop: plan the work, coordinate delivery, and review evidence. Members create and assign tasks, explain blockers, schedule meetings and RSVP. Each successful action adds an immutable event, so totals always lead back to context."],
        ["4 · 2:00-3:10", "Speaker C", "The task board shows ownership and risk at a glance. Task detail keeps assignments, workflow and discussion together. The contribution view compares activity using both a chart and table, but deliberately avoids grading. Selecting a member reveals the events behind each total."],
        ["5 · 3:10-4:00", "Speaker C", "The design is feasible and safe. Thirteen normalised PostgreSQL tables support explicit one-to-one, one-to-many and many-to-many relationships. Every protected request checks current membership. React, Express and PostgreSQL let us deliver in tested vertical slices."],
        ["6 · 4:00-4:50", "Speaker D", "Our approved baseline is authentication, private projects, tasks, comments, meetings, notifications and contribution evidence. We build those from weeks 7 to 10, integrate and test in weeks 10 to 11, then rehearse and harden in week 12. Search and export remain stretch goals until the core passes."],
        ["Close · 4:50-5:00", "Speaker D", "StudyCrew does not judge who worked hardest. It gives teams the shared facts to notice risk earlier, coordinate better and have fairer conversations. We are ready to validate the MVP and begin implementation."],
    ]
    doc.add_heading("Rehearsal script", level=1)
    add_text_table(doc, ["Slide / time", "Presenter", "Talk track"], script_rows, [1500, 1300, 6560], 8.7)
    doc.add_heading("Hand-off cues", level=1)
    add_text_table(doc, ["From", "Cue", "To"], [["A", "So what changes when planning and evidence share one workflow?", "B"], ["B", "The wireframes show how that loop feels in practice.", "C"], ["C", "A clear interface only matters if the system is feasible to build.", "C (technical)"], ["C", "That architecture gives us a disciplined delivery plan.", "D"]], [1200, 6660, 1500], 9)
    doc.add_heading("Likely Q&A", level=1)
    qa = [
        ["Is this just Trello?", "Task planning is familiar, but StudyCrew integrates meeting response and traceable contribution evidence designed for student teams."],
        ["Do activity counts prove contribution quality?", "No. We explicitly avoid scoring or grading; counts are starting points with drill-down context."],
        ["How do you stop students gaming the activity feed?", "The feed records action types and context, not a score. Teams inspect source events; meaningless volume gains no automatic advantage."],
        ["Why 13 tables?", "Each table has one responsibility. Junction tables prevent repeating groups and support the required many-to-many relationships without duplication."],
        ["How is privacy enforced?", "Every server-side project read and mutation checks validated session identity and current membership; exports recheck access at download time."],
        ["What happens if scope slips?", "Search and export are already outside the approved baseline. We freeze the MVP and protect core acceptance and security gates."],
        ["Can the team finish this?", "The system is split into four vertical slices with explicit tables, views and acceptance tests; no external paid API is required."],
        ["What is the innovation?", "Evidence is captured as a natural by-product of coordination, remains inspectable and is intentionally separated from automated judgement."],
    ]
    add_text_table(doc, ["Question", "Answer"], qa, [3000, 6360], 8.5)
    doc.add_heading("Final rehearsal checklist", level=1)
    add_text_table(doc, ["Check", "Pass condition"], [["Timing", "Two full rehearsals finish between 4:50 and 5:00"], ["Participation", "Every member has a speaking segment and can answer one technical and one product question"], ["Slides", "No presenter reads visible text; transitions reference the next claim"], ["Fallback", "Deck exported to PDF and available offline"], ["Q&A", "Every member can explain the MVP boundary, ERD relationships and evidence-not-grading principle"]], [2400, 6960], 9)
    path = OUT / "StudyCrew_Presentation_Script.docx"
    doc.save(path)
    return path


if __name__ == "__main__":
    outputs = [build_report(), build_mvp(), build_contract(), build_script()]
    for output in outputs:
        print(output)
