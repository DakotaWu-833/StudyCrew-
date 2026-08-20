import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const root = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(root, "build", "qa", "slides");
const deckPath = path.join(root, "deliverables", "StudyCrew_Milestone_Presentation.pptx");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(path.dirname(deckPath), { recursive: true });

const W = 1280;
const H = 720;
const C = {
  ink: "#12263A",
  blue: "#2774C7",
  pale: "#EAF2FA",
  paper: "#F7F5EF",
  white: "#FFFFFF",
  gray: "#667482",
  line: "#CBD5DF",
  coral: "#E96B4B",
  mint: "#BFE2D4",
  dark: "#0B1825",
};

const deck = Presentation.create({ slideSize: { width: W, height: H } });
deck.theme.colorScheme = {
  name: "StudyCrew Editorial",
  themeColors: {
    accent1: C.blue, accent2: C.coral, accent3: C.mint, accent4: "#D8A72A",
    accent5: "#4D7C78", accent6: "#8A6F4D", bg1: C.paper, bg2: C.pale,
    tx1: C.ink, tx2: C.gray, dk1: C.dark, dk2: C.ink, lt1: C.white,
    lt2: C.pale, hlink: C.blue, folHlink: C.coral,
  },
};

function rect(slide, left, top, width, height, fill, radius = 0, line = "none") {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function textBox(slide, text, left, top, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontFamily: options.fontFamily || "Aptos",
    fontSize: options.fontSize || 22,
    bold: options.bold || false,
    color: options.color || C.ink,
    ...(options.italic ? { italic: true } : {}),
  };
  return shape;
}

function heading(slide, number, title, strap = "") {
  textBox(slide, number, 1000, 42, 222, 24, { fontSize: 15, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
  textBox(slide, title, 58, 82, 1100, 72, { fontSize: 42, bold: true, fontFamily: "Bahnschrift" });
  rect(slide, 58, 160, 1164, 3, C.blue);
  if (strap) textBox(slide, strap, 58, 174, 1100, 38, { fontSize: 17, color: C.gray });
}

function footer(slide, n) {
  textBox(slide, "STUDYCREW  |  ELEC3609/9609  |  GROUP 02", 58, 682, 520, 20, { fontSize: 11, bold: true, color: C.gray, fontFamily: "Bahnschrift" });
  textBox(slide, String(n).padStart(2, "0"), 1168, 682, 54, 20, { fontSize: 11, bold: true, color: C.gray, fontFamily: "Bahnschrift" });
}

function notes(slide, body, sources) {
  slide.speakerNotes.textFrame.setText(`${body}\n\n[Sources]\n${sources.map((source) => `- ${source}`).join("\n")}\n[/Sources]`);
  slide.speakerNotes.setVisible(true);
}

// Slide 1: sparse cover, following the Codex Grid title hierarchy.
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  rect(slide, 0, 0, 16, H, C.blue);
  textBox(slide, "STUDYCREW", 72, 66, 240, 34, { fontSize: 17, bold: true, color: C.mint, fontFamily: "Bahnschrift" });
  textBox(slide, "Make group work\nvisible before it\nbecomes a problem.", 72, 150, 890, 270, { fontSize: 62, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  rect(slide, 72, 456, 290, 6, C.coral);
  textBox(slide, "One private workflow for planning, coordination and inspectable contribution evidence.", 72, 486, 730, 78, { fontSize: 24, color: "#D8E3EC" });
  rect(slide, 958, 126, 220, 404, C.blue, 22);
  textBox(slide, "PLAN", 992, 174, 150, 36, { fontSize: 24, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "COORDINATE", 992, 284, 170, 36, { fontSize: 24, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "PROVE", 992, 394, 150, 36, { fontSize: 24, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "not grade", 992, 438, 150, 28, { fontSize: 16, italic: true, color: C.mint });
  textBox(slide, "ELEC3609/9609  ·  ASSIGNMENT 1  ·  GROUP 02", 72, 662, 540, 22, { fontSize: 12, bold: true, color: "#A8BAC9", fontFamily: "Bahnschrift" });
  notes(slide,
    "0:00-0:25 · Speaker A\nStudyCrew makes group work visible before it becomes a problem. It gives student teams one place to coordinate tasks and meetings, then backs contribution conversations with transparent activity evidence.",
    ["Assignment brief supplied by the unit, 2026.", "StudyCrew System Design Report, Section 1."]);
}

// Slide 2: two-column tension slide.
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  heading(slide, "01 / PROBLEM", "Group work fails quietly before it fails visibly.", "Two disconnected problems reinforce each other.");
  rect(slide, 58, 236, 548, 354, C.white, 18, C.line);
  rect(slide, 624, 236, 598, 354, C.ink, 18);
  textBox(slide, "COORDINATION", 92, 270, 250, 28, { fontSize: 14, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
  textBox(slide, "Work is split across\nchat, calendars and\ntask lists.", 92, 318, 420, 132, { fontSize: 32, bold: true, fontFamily: "Bahnschrift" });
  textBox(slide, "Status becomes stale. Blockers surface near submission.", 92, 484, 420, 58, { fontSize: 19, color: C.gray });
  textBox(slide, "CONTRIBUTION", 662, 270, 250, 28, { fontSize: 14, bold: true, color: C.mint, fontFamily: "Bahnschrift" });
  textBox(slide, "Teams reconstruct\nwho did what from\nmemory.", 662, 318, 430, 132, { fontSize: 32, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "Late disputes lack shared facts and context.", 662, 484, 430, 58, { fontSize: 19, color: "#D8E3EC" });
  rect(slide, 514, 548, 194, 42, C.coral, 20);
  textBox(slide, "ONE WORKFLOW", 539, 559, 160, 22, { fontSize: 13, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  footer(slide, 2);
  notes(slide,
    "0:25-1:05 · Speaker A\nToday, work is often split across chat, calendars and task lists. Status becomes stale, blockers surface late, and contribution discussions depend on memory. Teams need coordination and evidence together, without a black-box score.",
    ["StudyCrew System Design Report, Section 1.1.", "Team problem synthesis based on the assignment context."]);
}

// Slide 3: process flow with one clear loop.
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  heading(slide, "02 / RESPONSE", "A simple loop: plan, coordinate, review evidence.", "Every meaningful action retains its context.");
  const cards = [
    { x: 58, n: "01", title: "PLAN", body: "Create projects.\nAssign tasks.\nSet ownership.", fill: C.white },
    { x: 424, n: "02", title: "COORDINATE", body: "Progress work.\nDiscuss blockers.\nSchedule and RSVP.", fill: C.pale },
    { x: 790, n: "03", title: "REVIEW", body: "See activity totals.\nDrill into events.\nHave the conversation.", fill: C.white },
  ];
  for (const card of cards) {
    rect(slide, card.x, 246, 326, 286, card.fill, 18, C.line);
    textBox(slide, card.n, card.x + 28, 272, 66, 36, { fontSize: 17, bold: true, color: C.coral, fontFamily: "Bahnschrift" });
    textBox(slide, card.title, card.x + 28, 326, 250, 38, { fontSize: 27, bold: true, fontFamily: "Bahnschrift" });
    textBox(slide, card.body, card.x + 28, 384, 260, 112, { fontSize: 21, color: C.gray });
  }
  textBox(slide, "→", 389, 350, 34, 48, { fontSize: 34, bold: true, color: C.blue });
  textBox(slide, "→", 755, 350, 34, 48, { fontSize: 34, bold: true, color: C.blue });
  rect(slide, 58, 560, 1058, 70, C.ink, 14);
  textBox(slide, "IMMUTABLE ACTIVITY EVENTS", 88, 581, 350, 28, { fontSize: 17, bold: true, color: C.mint, fontFamily: "Bahnschrift" });
  textBox(slide, "Evidence, not an automated grade", 711, 580, 370, 28, { fontSize: 18, italic: true, color: C.white });
  footer(slide, 3);
  notes(slide,
    "1:05-2:00 · Speaker B\nStudyCrew follows a simple loop: plan the work, coordinate delivery, and review evidence. Members create and assign tasks, explain blockers, schedule meetings and RSVP. Each successful action adds an immutable event, so totals always lead back to context.",
    ["StudyCrew functional requirements FR-PROJ-01 through FR-CONTR-02.", "database/schema.sql: activity_events table and related foreign keys."]);
}

// Slide 4: real wireframe evidence rather than decorative mockups.
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  heading(slide, "03 / PRODUCT", "The workflow is already testable on paper.", "Two views demonstrate the core value proposition.");
  const taskBytes = await fs.readFile(path.join(root, "design", "generated", "wf-04-task-board.png"));
  const evidenceBytes = await fs.readFile(path.join(root, "design", "generated", "wf-08-contributions.png"));
  rect(slide, 58, 226, 552, 372, C.white, 16, C.line);
  rect(slide, 628, 226, 594, 372, C.white, 16, C.line);
  slide.images.add({ blob: taskBytes, contentType: "image/png", alt: "StudyCrew task board wireframe", fit: "contain", position: { left: 76, top: 244, width: 516, height: 288 } });
  slide.images.add({ blob: evidenceBytes, contentType: "image/png", alt: "StudyCrew contribution evidence wireframe", fit: "contain", position: { left: 646, top: 244, width: 558, height: 288 } });
  textBox(slide, "TASK BOARD", 82, 548, 180, 26, { fontSize: 15, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
  textBox(slide, "Ownership, due dates and blockers at a glance", 230, 548, 340, 28, { fontSize: 15, color: C.gray });
  textBox(slide, "EVIDENCE", 652, 548, 160, 26, { fontSize: 15, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
  textBox(slide, "Counts reconcile to inspectable source events", 775, 548, 405, 28, { fontSize: 15, color: C.gray });
  footer(slide, 4);
  notes(slide,
    "2:00-3:10 · Speaker C\nThe task board shows ownership and risk at a glance. Task detail keeps assignments, workflow and discussion together. The contribution view compares activity using both a chart and table, but deliberately avoids grading. Selecting a member reveals the events behind each total.",
    ["design/generated/wf-04-task-board.png.", "design/generated/wf-08-contributions.png.", "StudyCrew traceability matrix, FR-TASK-01/02/03 and FR-CONTR-01/02."]);
}

// Slide 5: data integrity and feasibility.
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  heading(slide, "04 / TRUST", "The data model makes the promise enforceable.", "Normalised relationships, explicit constraints and a project access boundary.");
  const metrics = [
    { x: 58, value: "13", label: "normalised tables" },
    { x: 286, value: "18", label: "traceable requirements" },
    { x: 514, value: "11", label: "generic views" },
  ];
  for (const item of metrics) {
    rect(slide, item.x, 226, 204, 118, C.white, 16, C.line);
    textBox(slide, item.value, item.x + 24, 242, 86, 52, { fontSize: 40, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
    textBox(slide, item.label, item.x + 24, 299, 160, 26, { fontSize: 14, color: C.gray });
  }
  rect(slide, 760, 226, 462, 288, C.ink, 18);
  textBox(slide, "REQUIRED CARDINALITIES", 790, 254, 330, 28, { fontSize: 15, bold: true, color: C.mint, fontFamily: "Bahnschrift" });
  textBox(slide, "users  1 : 1  profiles", 790, 310, 340, 34, { fontSize: 23, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "projects  1 : N  tasks", 790, 372, 340, 34, { fontSize: 23, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  textBox(slide, "tasks  M : N  users", 790, 434, 340, 34, { fontSize: 23, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  rect(slide, 58, 380, 660, 134, C.pale, 16);
  textBox(slide, "SECURITY BOUNDARY", 86, 404, 240, 26, { fontSize: 15, bold: true, color: C.blue, fontFamily: "Bahnschrift" });
  textBox(slide, "Every protected request validates the session, current project membership and role before reading or changing data.", 86, 444, 588, 58, { fontSize: 18, color: C.ink });
  rect(slide, 58, 548, 1164, 74, C.white, 14, C.line);
  textBox(slide, "BUILD STACK", 84, 572, 150, 24, { fontSize: 14, bold: true, color: C.coral, fontFamily: "Bahnschrift" });
  textBox(slide, "React  ·  Express  ·  PostgreSQL + Prisma  ·  Vitest + Playwright  ·  Docker + GitHub Actions", 236, 570, 930, 28, { fontSize: 17, bold: true, fontFamily: "Bahnschrift" });
  footer(slide, 5);
  notes(slide,
    "3:10-4:00 · Speaker C\nThe design is feasible and safe. Thirteen normalised PostgreSQL tables support explicit one-to-one, one-to-many and many-to-many relationships. Every protected request checks current membership. React, Express and PostgreSQL let us deliver in tested vertical slices.",
    ["database/schema.sql, PostgreSQL 16 physical schema.", "StudyCrew System Design Report, Sections 3 and 6.", "IEEE Std 830-1998 is used because the assignment explicitly requests Section 5.3.2."]);
}

// Slide 6: final-minute implementation plan and Gantt.
{
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  heading(slide, "05 / DELIVERY", "Freeze the MVP. Deliver tested vertical slices.", "Weeks 5-12, with search and export held behind the core quality gates.");
  const weeks = ["W5", "W6", "W7", "W8", "W9", "W10", "W11", "W12"];
  const startX = 346;
  const colW = 100;
  weeks.forEach((week, index) => {
    textBox(slide, week, startX + index * colW, 232, 60, 24, { fontSize: 13, bold: true, color: C.gray, fontFamily: "Bahnschrift" });
    rect(slide, startX + index * colW, 262, 1, 286, C.line);
  });
  const rows = [
    { y: 278, label: "Validate + freeze", start: 0, span: 1, fill: C.coral },
    { y: 344, label: "Core vertical slices", start: 1, span: 4, fill: C.blue },
    { y: 410, label: "Integrate + test", start: 5, span: 2, fill: C.ink },
    { y: 476, label: "Rehearse + harden", start: 7, span: 1, fill: "#4D7C78" },
  ];
  for (const row of rows) {
    textBox(slide, row.label, 58, row.y + 6, 250, 28, { fontSize: 17, bold: true, fontFamily: "Bahnschrift" });
    rect(slide, startX + row.start * colW + 6, row.y, row.span * colW - 14, 42, row.fill, 16);
  }
  rect(slide, 58, 572, 1164, 64, C.ink, 12);
  textBox(slide, "MVP DECISION", 84, 592, 170, 24, { fontSize: 14, bold: true, color: C.mint, fontFamily: "Bahnschrift" });
  textBox(slide, "Approve the 15-requirement baseline; keep search and export as gated stretch work.", 260, 590, 900, 28, { fontSize: 19, bold: true, color: C.white, fontFamily: "Bahnschrift" });
  footer(slide, 6);
  notes(slide,
    "4:00-4:50 · Speaker D\nOur approved baseline is authentication, private projects, tasks, comments, meetings, notifications and contribution evidence. We build those from weeks 7 to 10, integrate and test in weeks 10 to 11, then rehearse and harden in week 12. Search and export remain stretch goals until the core passes.\n\n4:50-5:00 close\nStudyCrew does not judge who worked hardest. It gives teams the shared facts to notice risk earlier, coordinate better, and have fairer conversations. We are ready to validate the MVP and begin implementation.",
    ["StudyCrew Proposed MVP, approved-baseline candidate.", "Assignment brief: milestone and final submission schedule.", "StudyCrew Presentation Script, rehearsal timings."]);
}

for (const [index, slide] of deck.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await deck.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(outputDir, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(outputDir, `${stem}.layout.json`), await layout.text());
}

const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(outputDir, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(deckPath);
console.log(`Created ${deckPath} with ${deck.slides.items.length} slides`);
