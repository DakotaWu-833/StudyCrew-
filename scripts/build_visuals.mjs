import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import sharp from "sharp";

const root = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(root, "design", "generated");
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
});

const css = `
  * { box-sizing: border-box; }
  body { margin: 0; background: #fff; color: #161616; font-family: Arial, sans-serif; }
  .sheet { position: relative; width: 1800px; height: 1100px; overflow: hidden; background: #fff; }
  .sheet-title { position: absolute; left: 44px; top: 30px; font-size: 28px; font-weight: 700; }
  .sheet-subtitle { position: absolute; left: 44px; top: 68px; font-size: 15px; color: #555; }
  .entity { position: absolute; border: 2px solid #202020; background: #fff; z-index: 2; box-shadow: 4px 4px 0 #ddd; }
  .entity h2 { margin: 0; padding: 10px 12px; background: #1d1d1d; color: #fff; font-size: 21px; letter-spacing: .2px; }
  .entity .field { display: grid; grid-template-columns: 48px 1fr; gap: 5px; padding: 4px 9px; border-top: 1px solid #ddd; font: 17px/1.15 Consolas, monospace; white-space: nowrap; }
  .entity .key { font-weight: 700; }
  .edges { position: absolute; inset: 0; z-index: 1; }
  .edge { stroke: #555; stroke-width: 2; fill: none; }
  .edge-label { font: 13px Arial, sans-serif; fill: #333; paint-order: stroke; stroke: #fff; stroke-width: 5px; stroke-linejoin: round; }
  .legend { position: absolute; right: 42px; top: 28px; font-size: 14px; border: 1px solid #777; padding: 8px 12px; background: #fff; z-index: 3; }
  .note { position: absolute; left: 44px; bottom: 24px; width: 1710px; font-size: 13px; color: #555; }
`;

function entity(name, x, y, w, fields) {
  return `<section class="entity" style="left:${x}px;top:${y}px;width:${w}px">
    <h2>${name}</h2>
    ${fields.map(([key, text]) => `<div class="field"><span class="key">${key}</span><span>${text}</span></div>`).join("")}
  </section>`;
}

const markerDefs = `
  <defs>
    <marker id="oneStart" markerWidth="18" markerHeight="20" refX="2" refY="10" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M2 2V18 M8 2V18" stroke="#555" stroke-width="2" fill="none"/>
    </marker>
    <marker id="oneEnd" markerWidth="18" markerHeight="20" refX="16" refY="10" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M16 2V18 M10 2V18" stroke="#555" stroke-width="2" fill="none"/>
    </marker>
    <marker id="manyStart" markerWidth="22" markerHeight="24" refX="2" refY="12" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M2 3V21 M8 12L19 3 M8 12L19 21 M8 12H20" stroke="#555" stroke-width="2" fill="none"/>
    </marker>
    <marker id="manyEnd" markerWidth="22" markerHeight="24" refX="20" refY="12" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M20 3V21 M14 12L3 3 M14 12L3 21 M14 12H2" stroke="#555" stroke-width="2" fill="none"/>
    </marker>
  </defs>`;

function edge(x1, y1, x2, y2, start, end, label, lx, ly, bend) {
  const d = bend
    ? `M${x1},${y1} L${bend},${y1} L${bend},${y2} L${x2},${y2}`
    : `M${x1},${y1} L${x2},${y2}`;
  return `<path class="edge" d="${d}" marker-start="url(#${start})" marker-end="url(#${end})"/>
    <text class="edge-label" x="${lx}" y="${ly}">${label}</text>`;
}

function rawEdge(d, start, end, label, lx, ly) {
  return `<path class="edge" d="${d}" marker-start="url(#${start})" marker-end="url(#${end})"/>
    <text class="edge-label" x="${lx}" y="${ly}">${label}</text>`;
}

const shared = {
  users: [["PK", "user_id uuid"], ["UQ", "email varchar(254)"], ["", "password_hash varchar(255)"], ["", "account_status varchar(16)"], ["", "created_at timestamptz"], ["", "last_login_at timestamptz NULL"]],
  profiles: [["PK/FK", "user_id uuid"], ["", "display_name varchar(80)"], ["", "course_code varchar(20) NULL"], ["", "time_zone varchar(64)"], ["", "biography varchar(500) NULL"], ["", "avatar_url varchar(2048) NULL"], ["", "updated_at timestamptz"]],
  projects: [["PK", "project_id uuid"], ["", "name varchar(100)"], ["", "description varchar(2000) NULL"], ["", "due_at timestamptz NULL"], ["FK", "created_by uuid"], ["", "created_at timestamptz"], ["", "archived_at timestamptz NULL"]],
};

const erds = [
  {
    file: "erd-1-identity-projects.png",
    crops: [[0, 1200], [600, 1200]],
    title: "Physical ERD 1/3 - Identity and project membership",
    subtitle: "PostgreSQL 16 types | Crow's Foot cardinality | PK, FK and UQ constraints shown",
    entities: [
      entity("users", 80, 160, 360, shared.users),
      entity("profiles", 80, 630, 360, shared.profiles),
      entity("projects", 700, 150, 390, shared.projects),
      entity("project_members", 1320, 145, 400, [["PK/FK", "project_id uuid"], ["PK/FK", "user_id uuid"], ["", "role varchar(16)"], ["", "joined_at timestamptz"], ["", "removed_at timestamptz NULL"]]),
      entity("project_invitations", 1240, 610, 480, [["PK", "invitation_id uuid"], ["FK", "project_id uuid"], ["", "invited_email varchar(254)"], ["FK", "invited_by uuid"], ["", "status varchar(16)"], ["UQ", "token_hash varchar(255)"], ["", "expires_at timestamptz"], ["", "responded_at timestamptz NULL"], ["", "created_at timestamptz"]]),
    ],
    edges: [
      edge(260, 390, 260, 630, "oneStart", "oneEnd", "has exactly one", 275, 520),
      edge(440, 250, 700, 250, "oneStart", "manyEnd", "creates 0..*", 505, 236),
      rawEdge("M440,310 L590,310 L590,520 L1210,520 L1210,310 L1320,310", "oneStart", "manyEnd", "joins via", 840, 506),
      edge(1090, 280, 1320, 280, "oneStart", "manyEnd", "contains 1..*", 1125, 266),
      edge(1090, 360, 1240, 690, "oneStart", "manyEnd", "has 0..* invites", 1080, 530, 1165),
      rawEdge("M440,345 L540,345 L540,575 L1160,575 L1160,760 L1240,760", "oneStart", "manyEnd", "sends 0..*", 835, 562),
    ],
  },
  {
    file: "erd-2-tasks-collaboration.png",
    crops: [[0, 1250], [550, 1250]],
    title: "Physical ERD 2/3 - Tasks and collaboration",
    subtitle: "Anchor entities are repeated in light form to make every foreign-key relationship readable",
    entities: [
      entity("projects (anchor)", 70, 160, 330, [["PK", "project_id uuid"], ["", "name varchar(100)"]]),
      entity("users (anchor)", 70, 700, 330, [["PK", "user_id uuid"], ["UQ", "email varchar(254)"]]),
      entity("tasks", 650, 110, 470, [["PK", "task_id uuid"], ["FK", "project_id uuid"], ["", "title varchar(120)"], ["", "description varchar(4000) NULL"], ["", "status varchar(16)"], ["", "priority varchar(16)"], ["", "blocker_note varchar(500) NULL"], ["", "due_at timestamptz NULL"], ["", "completed_at timestamptz NULL"], ["FK", "created_by uuid"], ["", "created_at timestamptz"], ["", "updated_at timestamptz"], ["", "archived_at timestamptz NULL"]]),
      entity("task_assignees", 1320, 165, 410, [["PK/FK", "task_id uuid"], ["PK/FK", "user_id uuid"], ["FK", "assigned_by uuid"], ["", "assigned_at timestamptz"]]),
      entity("task_comments", 1260, 650, 470, [["PK", "comment_id uuid"], ["FK", "task_id uuid"], ["FK", "author_id uuid"], ["", "body varchar(2000)"], ["", "created_at timestamptz"], ["", "edited_at timestamptz NULL"], ["", "deleted_at timestamptz NULL"], ["FK", "moderated_by uuid NULL"]]),
    ],
    edges: [
      edge(400, 235, 650, 235, "oneStart", "manyEnd", "owns 0..*", 470, 220),
      edge(400, 755, 650, 480, "oneStart", "manyEnd", "creates 0..*", 440, 570, 520),
      edge(1120, 260, 1320, 260, "oneStart", "manyEnd", "assigned through", 1140, 245),
      edge(400, 790, 1320, 335, "oneStart", "manyEnd", "is assigned 0..*", 830, 760, 1160),
      edge(1120, 520, 1260, 720, "oneStart", "manyEnd", "has 0..*", 1120, 640, 1190),
      edge(400, 820, 1260, 805, "oneStart", "manyEnd", "authors 0..*", 780, 806),
    ],
  },
  {
    file: "erd-3-meetings-evidence.png",
    height: 1280,
    crops: [[0, 1150], [450, 1350]],
    title: "Physical ERD 3/3 - Meetings, evidence and exports",
    subtitle: "Contribution totals are derived from immutable events; no duplicated score or total is stored",
    entities: [
      entity("users (anchor)", 65, 130, 315, [["PK", "user_id uuid"], ["UQ", "email varchar(254)"]]),
      entity("projects (anchor)", 65, 470, 315, [["PK", "project_id uuid"], ["", "name varchar(100)"]]),
      entity("meetings", 510, 95, 430, [["PK", "meeting_id uuid"], ["FK", "project_id uuid"], ["", "title varchar(120)"], ["", "starts_at timestamptz"], ["", "ends_at timestamptz"], ["", "location_or_url varchar(2048) NULL"], ["", "agenda varchar(4000) NULL"], ["FK", "organised_by uuid"], ["", "created_at timestamptz"], ["", "updated_at timestamptz"], ["", "cancelled_at timestamptz NULL"]]),
      entity("meeting_attendees", 1090, 110, 430, [["PK/FK", "meeting_id uuid"], ["PK/FK", "user_id uuid"], ["", "response varchar(16)"], ["", "availability_note varchar(500) NULL"], ["", "responded_at timestamptz NULL"]]),
      entity("activity_events", 490, 620, 500, [["PK", "event_id bigint identity"], ["FK", "project_id uuid"], ["FK", "actor_id uuid"], ["", "event_type varchar(40)"], ["FK", "task_id uuid NULL"], ["FK", "comment_id uuid NULL"], ["FK", "meeting_id uuid NULL"], ["", "metadata jsonb"], ["", "occurred_at timestamptz"]]),
      entity("notifications", 1080, 565, 470, [["PK", "notification_id bigint identity"], ["FK", "recipient_id uuid"], ["FK", "project_id uuid"], ["UQ/FK", "source_event_id bigint"], ["", "notification_type varchar(24)"], ["", "created_at timestamptz"], ["", "read_at timestamptz NULL"]]),
      entity("export_jobs", 1320, 820, 420, [["PK", "export_job_id uuid"], ["FK", "project_id uuid"], ["FK", "requested_by uuid"], ["", "format varchar(8)"], ["", "range_start date"], ["", "range_end date"], ["", "status varchar(16)"], ["", "storage_key varchar(512) NULL"], ["", "error_message varchar(500) NULL"], ["", "requested_at timestamptz"], ["", "completed_at timestamptz NULL"], ["", "expires_at timestamptz NULL"]]),
    ],
    edges: [
      edge(380, 190, 510, 260, "oneStart", "manyEnd", "organises", 385, 235),
      edge(380, 535, 510, 350, "oneStart", "manyEnd", "schedules", 395, 430, 445),
      edge(940, 260, 1090, 260, "oneStart", "manyEnd", "has RSVPs", 970, 245),
      rawEdge("M380,230 L430,230 L430,430 L1030,430 L1030,350 L1090,350", "oneStart", "manyEnd", "responds via", 700, 417),
      edge(380, 570, 490, 700, "oneStart", "manyEnd", "records 0..*", 365, 650, 435),
      edge(990, 715, 1080, 715, "oneStart", "manyEnd", "triggers", 995, 700),
      rawEdge("M380,265 L410,265 L410,590 L1080,590", "oneStart", "manyEnd", "receives", 790, 578),
      rawEdge("M380,595 L430,595 L430,1070 L1260,1070 L1260,900 L1320,900", "oneStart", "manyEnd", "exports 0..*", 820, 1057),
    ],
  },
];

const page = await browser.newPage({ viewport: { width: 1800, height: 1180 }, deviceScaleFactor: 1 });
for (const erd of erds) {
  const height = erd.height || 1100;
  const html = `<style>${css}</style><main class="sheet" style="height:${height}px">
    <div class="sheet-title">${erd.title}</div><div class="sheet-subtitle">${erd.subtitle}</div>
    <div class="legend">Notation: <b>||</b> exactly one &nbsp; <b>|&lt;</b> one or many &nbsp; endpoint labels state optionality</div>
    <svg class="edges" width="1800" height="${height}">${markerDefs}${erd.edges.join("")}</svg>
    ${erd.entities.join("")}
  </main>`;
  await page.setContent(html);
  const fullPath = path.join(outputDir, erd.file);
  await page.locator(".sheet").screenshot({ path: fullPath });
  const stem = erd.file.replace(/\.png$/, "");
  const [[leftA, widthA], [leftB, widthB]] = erd.crops;
  await sharp(fullPath).extract({ left: leftA, top: 0, width: widthA, height }).toFile(path.join(outputDir, `${stem}-a.png`));
  await sharp(fullPath)
    .extract({ left: leftB, top: 0, width: widthB, height })
    .composite([{
      input: { create: { width: Math.min(600, widthB), height: 90, channels: 4, background: "#ffffff" } },
      left: 0,
      top: 0,
    }])
    .toFile(path.join(outputDir, `${stem}-b.png`));
}

const wfCss = `
  * { box-sizing: border-box; } body { margin:0; background:#fff; font-family:Arial,sans-serif; color:#191919; }
  .canvas { width:1440px; height:900px; background:#f4f4f4; padding:26px; position:relative; }
  .browser { height:760px; border:2px solid #111; background:#fff; overflow:hidden; }
  .chrome { height:42px; border-bottom:1px solid #777; display:flex; align-items:center; padding:0 14px; gap:8px; }
  .dot { width:10px; height:10px; border:1px solid #333; border-radius:50%; }
  .address { margin-left:16px; border:1px solid #999; height:24px; flex:1; padding:3px 12px; color:#666; font-size:12px; }
  .app { display:grid; grid-template-columns:210px 1fr; height:718px; }
  .sidebar { border-right:1px solid #888; padding:24px 18px; background:#fafafa; }
  .brand { font-size:22px; font-weight:700; margin-bottom:28px; }
  .nav { padding:10px 8px; margin:4px 0; border:1px solid transparent; }
  .nav.active { border-color:#111; background:#e8e8e8; font-weight:700; }
  .main { padding:30px 36px; overflow:hidden; }
  h1 { margin:0 0 8px; font-size:30px; } h2 { font-size:18px; margin:0 0 12px; }
  .sub { color:#666; margin-bottom:22px; }
  .row { display:flex; gap:18px; align-items:flex-start; } .grow { flex:1; }
  .card { border:1px solid #777; padding:16px; background:#fff; margin-bottom:14px; }
  .card.dashed { border-style:dashed; } .muted { color:#666; font-size:13px; }
  .btn { border:2px solid #111; background:#111; color:#fff; padding:9px 16px; display:inline-block; font-weight:700; font-size:13px; }
  .btn.secondary { background:#fff; color:#111; border-width:1px; }
  .field { border:1px solid #777; padding:10px 12px; margin:8px 0 14px; min-height:38px; color:#555; }
  .label { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; }
  .req { display:inline-block; border:1px solid #111; padding:2px 5px; font:11px Consolas,monospace; margin-left:5px; background:#fff; }
  .toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
  .search { border:1px solid #777; width:280px; padding:9px 12px; color:#666; }
  .cols { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
  .column { background:#f3f3f3; border-top:3px solid #333; padding:12px; min-height:450px; }
  .task { background:#fff; border:1px solid #888; padding:12px; margin:10px 0; }
  .tag { border:1px solid #777; padding:2px 5px; font-size:11px; display:inline-block; margin-right:4px; }
  .table { width:100%; border-collapse:collapse; } .table th,.table td { border-bottom:1px solid #aaa; padding:10px; text-align:left; font-size:13px; }
  .metric { flex:1; border-top:4px solid #111; padding:14px 4px; } .metric b { font-size:30px; display:block; }
  .bar { height:18px; background:#ddd; margin:7px 0; } .bar span { display:block; height:100%; background:#555; }
  .annotation { position:absolute; left:26px; right:26px; bottom:18px; border:1px solid #111; background:#fff; padding:12px 16px; font-size:13px; }
  .center { max-width:470px; margin:80px auto; }
  .no-side .app { grid-template-columns:1fr; }
  .split { display:grid; grid-template-columns:1.15fr .85fr; gap:22px; }
  .avatar { width:54px; height:54px; border:1px solid #222; border-radius:50%; display:grid; place-items:center; background:#eee; font-weight:700; }
`;

const sidebar = (active) => `<aside class="sidebar"><div class="brand">StudyCrew</div>${["Projects","Tasks","Meetings","Contributions","Notifications","Profile"].map(x=>`<div class="nav ${x===active?'active':''}">${x}</div>`).join("")}</aside>`;
const shell = (active, content, reqs, note="") => `<main class="canvas"><section class="browser"><div class="chrome"><i class="dot"></i><i class="dot"></i><i class="dot"></i><div class="address">studycrew.app</div></div><div class="app">${sidebar(active)}<section class="main">${content}</section></div></section><div class="annotation"><b>Requirements demonstrated:</b> ${reqs.map(r=>`<span class="req">${r}</span>`).join("")} ${note}</div></main>`;

const views = [
  ["wf-01-auth.png", `<main class="canvas no-side"><section class="browser"><div class="chrome"><i class="dot"></i><i class="dot"></i><i class="dot"></i><div class="address">studycrew.app/sign-in</div></div><div class="app"><section class="main"><div class="center"><div class="brand">StudyCrew</div><h1>Bring your group work into focus</h1><p class="sub">Sign in to continue, or create an account.</p><div class="label">University email</div><div class="field">student@uni.edu.au</div><div class="label">Password</div><div class="field">••••••••••••</div><span class="btn">Sign in</span> <span class="btn secondary">Create account</span><div class="card dashed" style="margin-top:24px"><b>Registration panel</b><p class="muted">Display name, email, password (12+ characters), field-level validation.</p></div></div></section></div></section><div class="annotation"><b>Requirements demonstrated:</b> <span class="req">FR-AUTH-01</span><span class="req">FR-AUTH-02</span> Generic visitor entry and validation state.</div></main>`],
  ["wf-02-dashboard.png", shell("Projects", `<div class="toolbar"><div><h1>Your projects</h1><div class="sub">Work that needs attention across every team.</div></div><span class="btn">+ New project <span class="req">FR-PROJ-01</span></span></div><div class="split"><div><div class="card"><h2>ELEC3609 · StudyCrew</h2><p>6 members · Due 13 Sep</p><div class="bar"><span style="width:62%"></span></div><small>8 of 13 tasks complete</small></div><div class="card"><h2>COMP2123 · Search visualiser</h2><p>4 members · Due 28 Sep</p><div class="bar"><span style="width:30%"></span></div></div></div><div><h2>Pending invitations <span class="req">FR-PROJ-02</span></h2><div class="card"><b>DATA2001 Team 7</b><p class="muted">Invited by Alex · expires in 5 days</p><span class="btn">Accept</span> <span class="btn secondary">Decline</span></div></div></div>`, ["FR-PROJ-01","FR-PROJ-02","FR-SEC-01"] )],
  ["wf-03-project-overview.png", shell("Projects", `<div class="toolbar"><div><h1>StudyCrew project</h1><div class="sub">A shared view of delivery risk and upcoming work.</div></div><span class="btn secondary">Project settings</span></div><div class="row"><div class="metric"><b>62%</b>tasks complete</div><div class="metric"><b>2</b>blocked tasks</div><div class="metric"><b>3</b>days to next meeting</div><div class="metric"><b>6</b>active members</div></div><div class="split" style="margin-top:28px"><div><h2>Needs attention</h2><div class="card"><b>ERD review is blocked</b><p class="muted">Waiting on role constraints · owner action requested</p></div><div class="card"><b>Wireframes due tomorrow</b><p class="muted">Assigned to Jamie and Sam</p></div></div><div><h2>Next meeting</h2><div class="card"><b>Design checkpoint</b><p>Fri 4:00 PM · Zoom</p><p class="muted">4 accepted · 1 pending · 1 declined</p></div><h2>Recent activity</h2><p class="muted">Jamie completed “User flows” · 14:32</p><p class="muted">Sam commented on “ERD review” · 13:18</p></div></div>`, ["FR-TASK-01","FR-MEET-01","FR-CONTR-01","FR-SEC-01"] )],
  ["wf-04-task-board.png", shell("Tasks", `<div class="toolbar"><div><h1>Task board</h1><div class="sub">StudyCrew project · 13 active tasks</div></div><span class="btn">+ Add task <span class="req">FR-TASK-01</span></span></div><div class="toolbar"><div class="search">Search titles and descriptions… <span class="req">FR-SEARCH-01</span></div><div><span class="btn secondary">Priority ▾</span> <span class="btn secondary">Assignee ▾</span> <span class="btn secondary">Due ▾</span></div></div><div class="cols"><div class="column"><b>TO DO · 3</b><div class="task"><b>Data dictionary</b><p class="muted">Due Fri</p><span class="tag">HIGH</span><span class="tag">AK</span></div></div><div class="column"><b>IN PROGRESS · 4</b><div class="task"><b>Dashboard wireframe</b><p class="muted">Jamie + Sam</p><span class="tag">MEDIUM</span></div></div><div class="column"><b>BLOCKED · 2</b><div class="task"><b>ERD review</b><p class="muted">Waiting on role constraints</p><span class="tag">URGENT</span></div></div><div class="column"><b>DONE · 4</b><div class="task"><b>User journeys</b><p class="muted">Completed today</p><span class="tag">LOW</span></div></div></div>`, ["FR-TASK-01","FR-TASK-02","FR-TASK-03","FR-SEARCH-01"] )],
  ["wf-05-task-detail.png", shell("Tasks", `<div class="toolbar"><div><p class="muted">Tasks / ERD review</p><h1>ERD review</h1></div><span class="btn secondary">Archive</span></div><div class="split"><div><div class="card"><div class="label">Description</div><p>Validate cardinalities, optionality, keys and PostgreSQL data types.</p><div class="row"><div class="grow"><div class="label">Status</div><div class="field">Blocked ▾ <span class="req">FR-TASK-03</span></div></div><div class="grow"><div class="label">Priority</div><div class="field">Urgent ▾</div></div></div><div class="label">Blocker note (required)</div><div class="field">Waiting on owner-role constraint decision</div><div class="label">Assignees <span class="req">FR-TASK-02</span></div><div class="field">AK · Jamie · + Add member</div></div></div><div><h2>Discussion <span class="req">FR-COLL-01</span></h2><div class="card"><b>Jamie</b><span class="muted"> · 13:18</span><p>Should the owner be represented by membership role?</p></div><div class="card"><b>AK</b><span class="muted"> · 13:24 · edited</span><p>Yes. A partial unique index guarantees one active owner.</p></div><div class="field">Write a comment… @mention a teammate</div><span class="btn">Comment</span></div></div>`, ["FR-TASK-01","FR-TASK-02","FR-TASK-03","FR-COLL-01","FR-NOTIF-01"] )],
  ["wf-06-members.png", shell("Projects", `<div class="toolbar"><div><h1>Members & invitations</h1><div class="sub">Owner-only controls are hidden from regular members.</div></div><span class="btn">Invite member <span class="req">FR-PROJ-02</span></span></div><table class="table"><thead><tr><th>Member</th><th>Role</th><th>Joined</th><th>Actions</th></tr></thead><tbody><tr><td><b>Alex Kim</b><br><span class="muted">alex@uni.edu.au</span></td><td>Owner</td><td>20 Aug</td><td>Sole owner · protected</td></tr><tr><td><b>Jamie Lee</b></td><td><span class="btn secondary">Facilitator ▾</span></td><td>20 Aug</td><td><span class="btn secondary">Remove</span></td></tr><tr><td><b>Sam Patel</b></td><td><span class="btn secondary">Member ▾</span></td><td>21 Aug</td><td><span class="btn secondary">Remove</span></td></tr></tbody></table><h2 style="margin-top:28px">Pending</h2><div class="card">newmember@uni.edu.au · expires 27 Aug <span class="btn secondary" style="float:right">Cancel invite</span></div>`, ["FR-PROJ-02","FR-PROJ-03","FR-SEC-01"] )],
  ["wf-07-meetings.png", shell("Meetings", `<div class="toolbar"><div><h1>Meetings</h1><div class="sub">Times display in Australia/Sydney.</div></div><span class="btn">+ Schedule meeting <span class="req">FR-MEET-01</span></span></div><div class="split"><div><div class="card"><p class="muted">FRI 28 AUG · 4:00-4:45 PM</p><h2>Design checkpoint</h2><p>Zoom · ERD, wireframe and requirement review</p><div class="row"><span class="btn">Accept</span><span class="btn secondary">Decline</span><span class="btn secondary">Pending</span></div><div class="field">Optional availability note…</div></div><div class="card"><p class="muted">TUE 1 SEP · 2:00-2:30 PM</p><h2>Pitch rehearsal</h2><p>J03.02.104</p></div></div><div><h2>Attendance <span class="req">FR-MEET-02</span></h2><table class="table"><tr><td>Alex</td><td>Accepted</td></tr><tr><td>Jamie</td><td>Accepted</td></tr><tr><td>Sam</td><td>Declined</td></tr><tr><td>Morgan</td><td>Pending</td></tr></table><div class="card dashed"><b>Edit or cancel</b><p class="muted">Organiser changes notify affected members while preserving RSVP evidence.</p></div></div></div>`, ["FR-MEET-01","FR-MEET-02","FR-NOTIF-01","FR-CONTR-01"] )],
  ["wf-08-contributions.png", shell("Contributions", `<div class="toolbar"><div><h1>Contribution evidence</h1><div class="sub">Transparent activity, not an automated grade.</div></div><span class="btn secondary">Export ▾ <span class="req">FR-EXPORT-01</span></span></div><div class="toolbar"><div><span class="btn secondary">20 Aug - 13 Sep ▾</span> <span class="btn secondary">All activities ▾</span></div><span class="muted">Updated from immutable activity events</span></div><div class="row"><div class="metric"><b>42</b>total events</div><div class="metric"><b>13</b>tasks completed</div><div class="metric"><b>28</b>comments</div><div class="metric"><b>91%</b>meeting responses</div></div><table class="table" style="margin-top:24px"><thead><tr><th>Member</th><th>Activity</th><th>Completed</th><th>Comments</th><th>Meetings</th></tr></thead><tbody><tr><td>Alex</td><td><div class="bar"><span style="width:85%"></span></div></td><td>4</td><td>8</td><td>3/3</td></tr><tr><td>Jamie</td><td><div class="bar"><span style="width:100%"></span></div></td><td>5</td><td>11</td><td>3/3</td></tr><tr><td>Sam</td><td><div class="bar"><span style="width:60%"></span></div></td><td>3</td><td>6</td><td>2/3</td></tr><tr><td>Morgan</td><td><div class="bar"><span style="width:30%"></span></div></td><td>1</td><td>3</td><td>2/3</td></tr></tbody></table><p class="muted">Select a member to inspect the underlying event list and reconcile totals.</p>`, ["FR-CONTR-01","FR-CONTR-02","FR-EXPORT-01","FR-SEC-01"] )],
  ["wf-09-notifications.png", shell("Notifications", `<div class="toolbar"><div><h1>Notifications</h1><div class="sub">3 unread · newest first</div></div><span class="btn secondary">Mark all read</span></div><div class="card"><b>Jamie assigned you “Dashboard wireframe”</b><span class="tag">UNREAD</span><p class="muted">StudyCrew project · 5 minutes ago</p><span class="btn secondary">Open task</span></div><div class="card"><b>Design checkpoint changed to 4:00 PM</b><span class="tag">UNREAD</span><p class="muted">StudyCrew project · 18 minutes ago</p><span class="btn secondary">Review meeting</span></div><div class="card"><b>You were invited to DATA2001 Team 7</b><span class="tag">UNREAD</span><p class="muted">2 hours ago · expires in 5 days</p><span class="btn secondary">Review invitation</span></div><div class="card"><b>Sam mentioned you in “ERD review”</b><p class="muted">Yesterday · read</p></div>`, ["FR-NOTIF-01","FR-SEC-01"], "Links are resolved through current authorisation; inaccessible sources are not exposed." )],
  ["wf-10-profile.png", shell("Profile", `<div class="toolbar"><div><h1>Your profile</h1><div class="sub">Used for team identity and meeting time display.</div></div><span class="btn">Save changes</span></div><div class="split"><div><div class="row"><div class="avatar">AK</div><div><b>Avatar URL</b><div class="field" style="width:420px">https://…/avatar.jpg</div></div></div><div class="label">Display name</div><div class="field">Alex Kim</div><div class="label">Course</div><div class="field">ELEC3609</div><div class="label">Time zone</div><div class="field">Australia/Sydney ▾</div><div class="label">Biography</div><div class="field" style="height:90px">Frontend and interaction design.</div></div><div class="card dashed"><h2>Privacy boundary</h2><p>Only current project teammates can see project-linked profile information.</p><p class="muted">Account email and password controls are not exposed on project pages.</p></div></div>`, ["FR-PROF-01","FR-SEC-01"] )],
  ["wf-11-export.png", shell("Contributions", `<h1>Export contribution evidence</h1><div class="sub">Create a time-bounded snapshot that can be reviewed outside StudyCrew.</div><div class="split"><div class="card"><div class="label">Project</div><div class="field">StudyCrew project</div><div class="label">Date range (maximum 366 days)</div><div class="row"><div class="field grow">20 Aug 2026</div><div class="field grow">13 Sep 2026</div></div><div class="label">Format</div><div class="field">PDF report ▾</div><span class="btn">Generate export</span></div><div><h2>Recent exports</h2><div class="card"><b>20 Aug - 13 Sep · PDF</b><p class="muted">Ready · expires in 23 hours</p><span class="btn secondary">Download</span></div><div class="card"><b>1 Aug - 19 Aug · CSV</b><p class="muted">Failed · no partial file retained</p><span class="btn secondary">Retry</span></div><p class="muted">Every download rechecks current project membership.</p></div></div>`, ["FR-EXPORT-01","FR-CONTR-02","FR-SEC-01"] )],
];

await page.setViewportSize({ width: 1440, height: 900 });
for (const [file, html] of views) {
  await page.setContent(`<style>${wfCss}</style>${html}`);
  await page.locator(".canvas").screenshot({ path: path.join(outputDir, file) });
}

await browser.close();
console.log(`Generated ${erds.length} ERDs and ${views.length} wireframes in ${outputDir}`);
