from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


requirements_text = (ROOT / "docs" / "requirements.md").read_text(encoding="utf-8")
requirement_ids = re.findall(r"^### (FR-[A-Z]+-\d+)", requirements_text, flags=re.MULTILINE)
expected_requirement_count = 19
require(
    len(requirement_ids) == expected_requirement_count,
    f"{expected_requirement_count} functional requirements are identified",
)
require(
    len(set(requirement_ids)) == expected_requirement_count,
    "functional requirement identifiers are unique",
)
require(
    requirements_text.lower().count("the system shall") >= expected_requirement_count,
    "every requirement uses mandatory shall language",
)

with (ROOT / "docs" / "traceability.csv").open(encoding="utf-8", newline="") as trace_file:
    trace_rows = list(csv.DictReader(trace_file))
trace_ids = [row["Requirement"] for row in trace_rows]
require(
    len(trace_ids) == len(requirement_ids) and set(trace_ids) == set(requirement_ids),
    "traceability covers every requirement exactly once",
)
require(all(row["Primary tables"] and row["Wireframe views"] for row in trace_rows), "every requirement maps to data and interface evidence")

schema_text = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
tables = re.findall(r"^CREATE TABLE ([a-z_]+)", schema_text, flags=re.MULTILINE)
require(len(tables) == 13, "physical schema contains 13 tables")
require("PRIMARY KEY (project_id, user_id)" in schema_text, "many-to-many project membership has a composite key")
require("PRIMARY KEY (task_id, user_id)" in schema_text, "many-to-many task assignment has a composite key")
require("user_id uuid PRIMARY KEY REFERENCES users" in schema_text, "users-to-profiles one-to-one relationship is enforced")
require("project_id uuid NOT NULL REFERENCES projects" in schema_text, "projects-to-dependent-records one-to-many relationship is enforced")

generated = ROOT / "design" / "generated"
require(len(list(generated.glob("erd-[1-3]-*.png"))) >= 6, "three complete ERDs and report crops are present")
require(len(list(generated.glob("wf-*.png"))) == 11, "11 generic-view wireframes are present")

pdf_expectations = {
    "StudyCrew_System_Design_Report.pdf": 27,
    "StudyCrew_MVP_Proposal.pdf": 3,
    "StudyCrew_Group_Contract_Working_Draft.pdf": 3,
    "StudyCrew_Presentation_Script.pdf": 3,
    "StudyCrew_Milestone_Presentation.pdf": 6,
}
for filename, expected_pages in pdf_expectations.items():
    pdf_path = ROOT / "deliverables" / filename
    require(pdf_path.exists() and pdf_path.stat().st_size > 10_000, f"{filename} exists and is non-trivial")
    reader = PdfReader(pdf_path)
    require(len(reader.pages) == expected_pages, f"{filename} has {expected_pages} pages")
    require(all((page.extract_text() or "").strip() for page in reader.pages), f"{filename} contains no blank pages")

pptx_path = ROOT / "deliverables" / "StudyCrew_Milestone_Presentation.pptx"
require(pptx_path.exists() and pptx_path.stat().st_size > 50_000, "editable milestone PPTX is present")
with zipfile.ZipFile(pptx_path) as deck:
    names = deck.namelist()
    slides = [name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
    note_names = [name for name in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)]
    require(len(slides) == 6, "PPTX contains six slides")
    require(len(note_names) == 6, "every slide has speaker notes")
    for note_name in note_names:
        note_xml = deck.read(note_name).decode("utf-8")
        require("[Sources]" in note_xml and "[/Sources]" in note_xml, f"{Path(note_name).name} has a source block")

print("\nAssignment 1 design-artifact audit passed.")
