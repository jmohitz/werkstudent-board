// Job board client: job list + sidebar filters, application tracker, resume matching,
// and a detail panel with resume tips and a tailored cover letter.
const PAGE = 100;
const CAT = {
  working_student: { code: "WS", label: "Working student" },
  internship: { code: "IN", label: "Internship" },
  thesis: { code: "TH", label: "Thesis" },
};
const FIELD = {
  software_engineering: "Software engineering",
  web_frontend: "Web / frontend",
  mobile: "Mobile",
  embedded_systems: "Embedded",
  data_engineering: "Data engineering",
  data_analytics_bi: "Data analytics / BI",
  data_science_ml: "Data science / ML",
  ai_llm: "AI / LLM",
  devops_cloud: "DevOps / cloud",
  security: "Security",
  qa_testing: "QA / testing",
  sap_erp: "SAP / ERP",
  research: "Research",
  other: "Other / unclassified",
};
const MODE = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site", unclear: "Not stated" };
const SITE = {
  linkedin: "LinkedIn", indeed: "Indeed", glassdoor: "Glassdoor", xing: "Xing", stepstone: "StepStone",
  jobware: "Jobware", arbeitnow: "Arbeitnow", jooble: "Jooble", arbeitsagentur: "Arbeitsagentur", fraunhofer: "Fraunhofer",
  berlinstartupjobs: "Berlin Startup Jobs", careers: "Startup career pages", google: "Google",
};
const STATUS = { saved: "Saved", applied: "Applied", interview: "Interview", offer: "Offer", rejected: "Rejected" };
const POSTED = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["3d", "Last 3 days"],
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
];
const LEVEL = { strong: "Strong fit", good: "Good fit", partial: "Partial fit", weak: "Weak fit" };

// one key per sidebar list; "" = no filter
const state = {
  category: "", posted: "", field: "", work_mode: "", site: "", status: "", english: false, q: "",
  sort: "newest", offset: 0, resume: null, openJob: null, demo: false,
};
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function ago(dateStr) {
  if (!dateStr) return "";
  const days = Math.floor((Date.now() - new Date(dateStr + "T00:00:00")) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

// ---------- job list ----------

function matchBadge(m) {
  if (m === null || m === undefined) return "";
  const cls = m >= 75 ? "hi" : m >= 45 ? "mid" : "lo";
  return `<span class="match ${cls}" title="Match with your resume">${m}%</span>`;
}

function tags(j) {
  const cat = CAT[j.category];
  const lang = j.german_required === null
    ? '<span class="tag dim" title="language requirement unclear">[DE?]</span>'
    : j.german_required ? '<span class="tag de">[DE]</span>' : '<span class="tag en">[EN]</span>';
  const field = j.field && j.field !== "other" ? `<span class="tag">[${esc(FIELD[j.field] ?? j.field)}]</span>` : "";
  const mode = j.work_mode && j.work_mode !== "unclear" ? `<span class="tag mode">[${esc(MODE[j.work_mode])}]</span>` : "";
  return `${cat ? `<span class="tag">[${cat.code}]</span>` : ""}${field}${lang}${mode}`;
}

function stackChips(stack, n = 6) {
  return (stack || []).slice(0, n).map((s) => `<span class="chip">${esc(s)}</span>`).join("");
}

function statusSelect(j) {
  const opts = [["", "Track…"], ...Object.entries(STATUS)]
    .map(([v, l]) => `<option value="${v}"${(j.status || "") === v ? " selected" : ""}>${l}</option>`)
    .join("");
  return `<select class="status${j.status ? " on" : ""}" data-job="${j.id}" aria-label="Application status">${opts}</select>`;
}

function jobRow(j) {
  const place = j.city || j.location || "";
  const hours = j.hours_per_week ? ` · ${j.hours_per_week}h/wk` : "";
  const stack = stackChips(j.stack);
  const detail = j.summary || stack
    ? `<div class="row detail"><span>${j.summary ? `<span class="dim">${esc(j.summary)}</span> ` : ""}${stack}</span></div>`
    : "";
  return `
    <li class="job" data-id="${j.id}">
      <div class="row">
        <span><a class="title" href="#job-${j.id}" data-open="${j.id}">${esc(j.title)}</a>
          <a class="ext" href="${esc(j.job_url)}" target="_blank" rel="noopener noreferrer" title="Open the posting">↗</a></span>
        <span>${matchBadge(j.match)} <span class="dim">${ago(j.posted)}</span></span>
      </div>
      <div class="row">
        <span>${tags(j)}
          <span class="company">${esc(j.company || "—")}</span>
          <span class="dim">· ${esc(place)}${hours} · ${esc(j.site || "")}</span></span>
        <span>${statusSelect(j)}</span>
      </div>
      ${detail}
    </li>`;
}

async function loadJobs(append = false) {
  if (!append) state.offset = 0;
  const p = new URLSearchParams({ limit: PAGE, offset: state.offset, sort: state.sort });
  for (const k of ["category", "posted", "field", "work_mode", "site", "status", "q"]) if (state[k]) p.set(k, state[k]);
  if (state.english) p.set("english_only", "true");

  try {
    const { total, jobs } = await api(`/api/jobs?${p}`);
    const list = $("jobs");
    const html = jobs.map(jobRow).join("");
    if (append) list.insertAdjacentHTML("beforeend", html);
    else list.innerHTML = html || '<li class="empty">No jobs match these filters.</li>';
    state.offset += jobs.length;
    $("count").textContent = `${total} found`;
    $("more").hidden = state.offset >= total;
  } catch (e) {
    $("jobs").innerHTML = `<li class="error">Could not load jobs (${esc(e.message)}). Is the API and database running?</li>`;
    $("more").hidden = true;
  }
}

// ---------- sidebar ----------

// Render one sidebar list. items: [[value, label, count]]; the first item is "all".
function renderList(key, items) {
  $(key).innerHTML = items.map(([value, label, n]) => `
    <li><button data-key="${key}" data-value="${esc(value)}" aria-pressed="${value === state[key]}">
      <span>${esc(label)}</span><span class="n">${n ?? ""}</span>
    </button></li>`).join("");
}

async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("total").textContent = s.total.toLocaleString();
    const tracked = Object.values(s.by_status).reduce((a, b) => a + b, 0);
    renderList("status", [["", "All jobs", s.total], ["tracked", "All tracked", tracked],
      ...Object.entries(STATUS).map(([k, l]) => [k, l, s.by_status[k] || 0])]);
    renderList("category", [["", "> All", s.total],
      ...s.by_category.map((c) => [c.key, `[${CAT[c.key]?.code ?? "?"}] ${CAT[c.key]?.label ?? c.key}`, c.n])]);
    renderList("posted", [["", "Any time", s.total], ...POSTED.map(([k, l]) => [k, l, s.by_posted[k]])]);
    renderList("field", [["", "All fields", s.total], ...s.by_field.map((f) => [f.key, FIELD[f.key] ?? f.key, f.n])]);
    renderList("site", [["", "All sources", s.total], ...s.by_site.map((x) => [x.key, SITE[x.key] ?? x.key, x.n])]);
    renderList("work_mode", [["", "Any", s.total], ...s.by_work_mode.map((m) => [m.key, MODE[m.key] ?? m.key, m.n])]);
    state.embeddings = s.embeddings;
    renderResume();
  } catch {
    $("total").textContent = "—";
  }
}

// ---------- resume ----------

async function loadConfig() {
  try { state.demo = (await api("/api/config")).demo; } catch { state.demo = false; }
  document.body.classList.toggle("demo", state.demo);
  if (state.demo) {
    $("resume").innerHTML = '<div class="dim small">Read-only demo: CV upload, matching, cover letters and the tracker are switched off.</div>';
  }
}

async function loadResume() {
  if (state.demo) return;
  try {
    state.resume = await api("/api/resume");  // null when none uploaded
  } catch {
    state.resume = null;
  }
  renderResume();
  document.querySelector('.sort button[data-sort="match"]').disabled = !state.resume;
}

function renderResume(msg = "") {
  if (state.demo) return;
  const r = state.resume;
  const e = state.embeddings;
  const paused = e?.last_error?.includes("daily");
  const progress = e && e.embedded < e.total
    ? `<div class="dim small">Matching ready for ${e.embedded.toLocaleString()} of ${e.total.toLocaleString()} jobs
       (${paused ? "free daily limit reached, continues tomorrow; unmatched jobs are listed last" : "more every minute"})</div>`
    : "";
  if (!r) {
    $("resume").innerHTML = `
      <div class="dim small">Upload your CV (PDF) to rank jobs by fit and get cover letters and resume tips.</div>
      <button class="btn" id="resume-upload">Upload resume</button>
      <div class="dim small">It is analysed with Google Gemini.</div>
      ${msg ? `<div class="small error-text">${esc(msg)}</div>` : ""}`;
    return;
  }
  const p = r.profile;
  $("resume").innerHTML = `
    <div class="small"><b>${esc(r.filename)}</b></div>
    <div class="dim small">${esc(p.headline || "")}</div>
    <div class="small">German: ${esc(p.german_level)}</div>
    <div class="chips">${stackChips(p.skills, 8)}</div>
    ${progress}
    <div class="btn-row"><button class="btn" id="resume-upload">Replace</button>
      <button class="btn ghost" id="resume-remove">Remove</button></div>
    ${msg ? `<div class="small error-text">${esc(msg)}</div>` : ""}`;
}

$("resume").addEventListener("click", async (e) => {
  if (e.target.id === "resume-upload") $("resume-file").click();
  if (e.target.id === "resume-remove") {
    if (!confirm("Remove your resume and all generated cover letters and tips?")) return;
    await api("/api/resume", { method: "DELETE" });
    state.resume = null;
    setSort("newest");
    loadResume();
    loadJobs();
  }
});

$("resume-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  $("resume").innerHTML = '<div class="dim small">Reading your resume… (takes ~10 s)</div>';
  const form = new FormData();
  form.append("file", file);
  try {
    state.resume = await api("/api/resume", { method: "POST", body: form });
    document.querySelector('.sort button[data-sort="match"]').disabled = false;
    renderResume();
    setSort("match");
    loadJobs();
  } catch (err) {
    renderResume(`Upload failed: ${err.message}`);
  }
});

function setSort(sort) {
  state.sort = sort;
  document.querySelectorAll(".sort button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.sort === sort));
}

document.querySelector(".sort").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-sort]");
  if (!btn || btn.disabled) return;
  setSort(btn.dataset.sort);
  loadJobs();
});

// ---------- detail panel: description, resume tips, cover letter ----------

function openDrawer() {
  $("drawer").hidden = false;
  $("backdrop").hidden = false;
  document.body.classList.add("drawer-open");
}

function closeDrawer() {
  $("drawer").hidden = true;
  $("backdrop").hidden = true;
  document.body.classList.remove("drawer-open");
  state.openJob = null;
}

async function openJob(id) {
  openDrawer();
  $("drawer-body").innerHTML = '<div class="dim">Loading…</div>';
  try {
    const j = await api(`/api/jobs/${id}`);
    state.openJob = j;
    renderJob(j);
  } catch (e) {
    $("drawer-body").innerHTML = `<div class="error">Could not load this job (${esc(e.message)}).</div>`;
  }
}

function renderJob(j) {
  const needResume = !state.resume
    ? '<div class="dim small">Upload your resume in the sidebar to use this.</div>'
    : "";
  const auto = j.posting_language === "de" ? "German" : "English";
  $("drawer-body").innerHTML = `
    <h2 class="d-title">${esc(j.title)}</h2>
    <div class="d-meta">${tags(j)} <span class="company">${esc(j.company || "—")}</span>
      <span class="dim">· ${esc(j.city || j.location || "")}${j.hours_per_week ? ` · ${j.hours_per_week}h/wk` : ""} · ${esc(j.site || "")} · ${ago(j.posted)}</span></div>
    <div class="d-actions">
      <a class="btn primary" href="${esc(j.job_url_direct || j.job_url)}" target="_blank" rel="noopener noreferrer">Open posting ↗</a>
      ${statusSelect(j)} ${matchBadge(j.match)}
    </div>
    ${j.summary ? `<p class="d-summary">${esc(j.summary)}</p>` : ""}
    ${j.stack?.length ? `<div class="chips">${stackChips(j.stack, 12)}</div>` : ""}

    <section class="d-section">
      <div class="d-section-head"><h3>Resume tips</h3>
        <button class="btn" id="tips-btn" ${state.resume ? "" : "disabled"}>Analyse fit</button></div>
      ${needResume}<div id="tips-out"></div>
    </section>

    <section class="d-section">
      <div class="d-section-head"><h3>Cover letter</h3>
        <span class="btn-row">
          <select id="cl-lang" aria-label="Cover letter language">
            <option value="auto">Auto (${auto})</option><option value="en">English</option><option value="de">Deutsch</option>
          </select>
          <button class="btn" id="cl-btn" ${state.resume ? "" : "disabled"}>Write cover letter</button>
        </span></div>
      ${needResume}<div id="cl-out"></div>
    </section>

    <details class="d-section" ${j.description ? "" : "open"}>
      <summary><h3>Job description</h3></summary>
      <div class="d-desc">${j.description ? esc(j.description) : '<span class="dim">No description stored for this job (older entry). Open the posting to read it.</span>'}</div>
    </details>`;
}

function renderTips(t) {
  const list = (title, items) => items?.length
    ? `<div class="t-block"><div class="t-title">${title}</div><ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  $("tips-out").innerHTML = `
    <div class="t-level ${t.match_level}">${LEVEL[t.match_level] ?? t.match_level}</div>
    <p>${esc(t.fit_summary)}</p>
    ${list("Strengths for this job", t.strengths)}
    ${list("Gaps", t.gaps)}
    ${list("What to change in your resume", t.resume_changes)}
    ${t.keywords?.length ? `<div class="t-block"><div class="t-title">Keywords to include (if true)</div><div class="chips">${stackChips(t.keywords, 12)}</div></div>` : ""}
    ${list("Prepare for the interview", t.interview_prep)}
    <div class="dim small">by ${esc(t.model)}${t.cached ? " · saved earlier" : ""} · <a href="#" id="tips-redo">regenerate</a></div>`;
}

function renderLetter(c) {
  const name = `cover-letter-${(state.openJob.company || "job").replace(/[^\w]+/g, "-").toLowerCase()}-${c.lang}.txt`;
  $("cl-out").innerHTML = `
    <textarea id="cl-text" rows="18" spellcheck="true">${esc(c.text)}</textarea>
    <div class="btn-row">
      <button class="btn" id="cl-copy">Copy</button>
      <a class="btn" id="cl-download" download="${esc(name)}">Download .txt</a>
      <span class="dim small">by ${esc(c.model)}${c.cached ? " · saved earlier" : ""} · edit freely before sending · <a href="#" id="cl-redo">regenerate</a></span>
    </div>`;
  const dl = () => { $("cl-download").href = URL.createObjectURL(new Blob([$("cl-text").value], { type: "text/plain" })); };
  dl();
  $("cl-text").addEventListener("input", dl);
}

async function runAI(kind, refresh = false) {
  const j = state.openJob;
  const out = kind === "tips" ? $("tips-out") : $("cl-out");
  const btn = kind === "tips" ? $("tips-btn") : $("cl-btn");
  btn.disabled = true;
  out.innerHTML = `<div class="dim small">${kind === "tips" ? "Comparing your resume with the posting" : "Writing your cover letter"}… (up to a minute)</div>`;
  try {
    if (kind === "tips") {
      renderTips(await api(`/api/jobs/${j.id}/tips?refresh=${refresh}`, { method: "POST" }));
    } else {
      const lang = $("cl-lang").value;
      renderLetter(await api(`/api/jobs/${j.id}/cover-letter?lang=${lang}&refresh=${refresh}`, { method: "POST" }));
    }
  } catch (e) {
    out.innerHTML = `<div class="small error-text">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

$("drawer-body").addEventListener("click", async (e) => {
  const id = e.target.id;
  if (id === "tips-btn") runAI("tips");
  if (id === "cl-btn") runAI("cover_letter");
  if (id === "tips-redo") { e.preventDefault(); runAI("tips", true); }
  if (id === "cl-redo") { e.preventDefault(); runAI("cover_letter", true); }
  if (id === "cl-copy") {
    await navigator.clipboard.writeText($("cl-text").value);
    e.target.textContent = "Copied";
    setTimeout(() => { e.target.textContent = "Copy"; }, 1500);
  }
});

$("drawer-close").addEventListener("click", closeDrawer);
$("backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("drawer").hidden) closeDrawer(); });

// ---------- events ----------

$("jobs").addEventListener("click", (e) => {
  const open = e.target.closest("[data-open]");
  if (open) { e.preventDefault(); openJob(open.dataset.open); }
});

document.querySelector(".sidebar").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-key]");
  if (!btn) return;
  const key = btn.dataset.key;
  state[key] = btn.dataset.value;
  document.querySelectorAll(`#${key} button`).forEach((b) => b.setAttribute("aria-pressed", b === btn));
  if (key === "category") {
    $("path").textContent = state.category ? `~/${CAT[state.category]?.label.toLowerCase() ?? state.category}` : "~/all jobs";
  }
  loadJobs();
});

$("english").addEventListener("change", (e) => { state.english = e.target.checked; loadJobs(); });

// Application tracker: picking a status saves it; "Track…" stops tracking. Works in the list and the panel.
async function onStatusChange(e) {
  const sel = e.target.closest("select.status");
  if (!sel) return;
  const id = sel.dataset.job;
  sel.disabled = true;
  try {
    if (sel.value) {
      await api(`/api/applications/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: sel.value }),
      });
    } else {
      await api(`/api/applications/${id}`, { method: "DELETE" });
    }
    // keep the list row and the panel in sync
    document.querySelectorAll(`select.status[data-job="${id}"]`).forEach((s) => {
      s.value = sel.value;
      s.classList.toggle("on", !!sel.value);
    });
    loadStats();
  } catch (err) {
    alert(`Could not save status: ${err.message}`);
  } finally {
    sel.disabled = false;
  }
}
$("jobs").addEventListener("change", onStatusChange);
$("drawer-body").addEventListener("change", onStatusChange);

let timer;
$("q").addEventListener("input", (e) => {
  clearTimeout(timer);
  timer = setTimeout(() => { state.q = e.target.value.trim(); loadJobs(); }, 250);
});

$("more").addEventListener("click", () => loadJobs(true));

loadConfig().then(loadResume).then(() => {
  if (state.resume) setSort("match");
  loadJobs();
});
loadStats();
