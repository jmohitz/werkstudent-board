// Minimal job board client: fetch /api/jobs, render rows, filter by category/relevance/search.
const PAGE = 100;
const CAT = {
  working_student: { code: "WS", label: "Working student" },
  internship: { code: "IN", label: "Internship" },
  thesis: { code: "TH", label: "Thesis" },
};

const state = { category: "", q: "", minRel: 4, offset: 0 };
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

function jobRow(j) {
  const cat = CAT[j.category];
  const lang = j.german_required === null
    ? '<span class="tag dim" title="language requirement unclear">[DE?]</span>'
    : j.german_required ? '<span class="tag de">[DE]</span>' : '<span class="tag en">[EN]</span>';
  const field = j.field && j.field !== "other" ? `<span class="tag">[${esc(j.field.replace(/_/g, " "))}]</span>` : "";
  const rel = j.relevance ? `<span class="rel" title="relevance ${j.relevance}/5">${"★".repeat(j.relevance)}</span>` : "";
  return `
    <li class="job">
      <div class="row">
        <a class="title" href="${esc(j.job_url)}" target="_blank" rel="noopener noreferrer">${esc(j.title)}</a>
        <span class="dim">${ago(j.posted)}</span>
      </div>
      <div class="row">
        <span>${cat ? `<span class="tag">[${cat.code}]</span>` : ""}${field}${lang}
          <span class="company">${esc(j.company || "—")}</span>
          <span class="dim loc-mobile">· ${esc(j.location || "")}</span>
          <span class="dim">· ${esc(j.site || "")}</span></span>
        <span class="dim">${esc(j.location || "")} ${rel}</span>
      </div>
    </li>`;
}

async function loadJobs(append = false) {
  if (!append) state.offset = 0;
  const p = new URLSearchParams({ limit: PAGE, offset: state.offset, min_relevance: state.minRel });
  if (state.category) p.set("category", state.category);
  if (state.q) p.set("q", state.q);

  try {
    const res = await fetch(`/api/jobs?${p}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { total, jobs } = await res.json();
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

async function loadStats() {
  try {
    const { total, by_category } = await (await fetch("/api/stats")).json();
    $("total").textContent = total.toLocaleString();
    const items = [{ category: "", n: total }, ...by_category];
    $("cats").innerHTML = items.map((c) => `
      <li><button data-cat="${esc(c.category)}" aria-pressed="${c.category === state.category}">
        <span>${c.category ? `[${CAT[c.category]?.code ?? "?"}] ${esc(CAT[c.category]?.label ?? c.category)}` : "> All"}</span>
        <span class="n">${c.n}</span>
      </button></li>`).join("");
  } catch {
    $("total").textContent = "—";
  }
}

$("cats").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.category = btn.dataset.cat;
  document.querySelectorAll("#cats button").forEach((b) => b.setAttribute("aria-pressed", b === btn));
  $("path").textContent = state.category ? `~/${CAT[state.category]?.label.toLowerCase() ?? state.category}` : "~/all jobs";
  loadJobs();
});

$("minrel").addEventListener("change", (e) => { state.minRel = Number(e.target.value); loadJobs(); });

let timer;
$("q").addEventListener("input", (e) => {
  clearTimeout(timer);
  timer = setTimeout(() => { state.q = e.target.value.trim(); loadJobs(); }, 250);
});

$("more").addEventListener("click", () => loadJobs(true));

loadStats();
loadJobs();
