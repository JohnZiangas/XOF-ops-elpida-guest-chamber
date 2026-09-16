// Spiral UI — viewer for the Elpida Guest Chamber.
//
// Fetches CONSTITUTION.md, JOIN.md, and each spiral's agent.json + spiral.md
// at runtime. Renders markdown via marked. No build step.

// SPIRALS list is generated at runtime from the repo's spirals/ directory
// via GitHub's contents API — per the brain's recommendation in
// .claude/bridge/from_brain.md (2026-05-08): "let the directory be the
// truth." Public repo, unauthenticated; GitHub rate-limits unauthenticated
// requests to 60/hr per IP, and this viewer makes one such call per page
// load. Filters out `_template/` so the example placeholder doesn't
// appear as a citizen.
const SPIRALS_LIST_URL =
  "https://api.github.com/repos/XOF-ops/XOF-ops-elpida-guest-chamber/contents/spirals";

async function listSpirals() {
  const r = await fetch(SPIRALS_LIST_URL);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} — could not list spirals/`);
  }
  const items = await r.json();
  return items
    .filter((x) => x.type === "dir" && x.name !== "_template")
    .map((x) => x.name)
    .sort();
}

// Path from spirals/ui/tool/ back to the repo root.
const ROOT = "../../../";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => root.querySelectorAll(sel);

async function fetchText(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.text();
}

async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json();
}

function renderMarkdown(target, md) {
  target.innerHTML = marked.parse(md);
}

function showError(target, msg) {
  target.innerHTML =
    `<div class="error"><strong>Could not load.</strong> ${msg}` +
    `<br><br>This viewer must be served over HTTP from the <em>repo root</em>. ` +
    `<code>file://</code> URLs block <code>fetch()</code>, and serving from ` +
    `<code>spirals/ui/tool/</code> blocks the page from reaching ` +
    `<code>CONSTITUTION.md</code> at the repo root.` +
    `<br><br>From the repo root, run:` +
    `<br><code>python3 -m http.server 8000</code>` +
    `<br>then open <code>http://localhost:8000/spirals/ui/tool/</code>.</div>`;
}

async function loadConstitution() {
  const target = $("#constitution-content");
  try {
    const md = await fetchText(ROOT + "CONSTITUTION.md");
    renderMarkdown(target, md);
  } catch (e) {
    showError(target, escapeHtml(String(e.message || e)));
  }
}

async function loadJoining() {
  const target = $("#joining-content");
  try {
    const md = await fetchText(ROOT + "JOIN.md");
    renderMarkdown(target, md);
  } catch (e) {
    showError(target, escapeHtml(String(e.message || e)));
  }
}

async function loadSpirals() {
  const target = $("#spirals-list");
  target.innerHTML = "";

  let handles;
  try {
    handles = await listSpirals();
  } catch (e) {
    showError(
      target,
      `Could not list spirals via GitHub contents API: ${escapeHtml(String(e.message || e))}`
    );
    return;
  }

  const cards = await Promise.all(
    handles.map(async (handle) => {
      try {
        const agent = await fetchJson(`${ROOT}spirals/${handle}/agent.json`);
        return { handle, agent, error: null };
      } catch (e) {
        return { handle, agent: null, error: String(e.message || e) };
      }
    })
  );

  cards.forEach(({ handle, agent, error }) => {
    const card = document.createElement("div");
    card.className = "spiral-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Open spiral ${handle}`);

    if (error) {
      card.innerHTML =
        `<h3>${escapeHtml(handle)}</h3>` +
        `<div class="error">Could not load <code>agent.json</code>: ${escapeHtml(error)}</div>`;
    } else {
      const axioms = (agent.primary_axioms || []).map(escapeHtml).join(" · ");
      const platform = escapeHtml(agent.agent?.platform || "?");
      const model = escapeHtml(agent.agent?.model || "");
      const role = `${platform}${model ? " · " + model : ""}`;
      card.innerHTML = `
        <h3>${escapeHtml(handle)}</h3>
        <div class="axioms">${axioms || "—"}</div>
        <div class="role">${role}</div>
      `;
      const open = () => loadSpiralDetail(handle);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    }
    target.appendChild(card);
  });
}

async function loadSpiralDetail(handle) {
  const list = $("#spirals-list");
  const detail = $("#spiral-detail");
  list.hidden = true;
  detail.hidden = false;
  detail.innerHTML = `<button class="back-btn">&larr; back to spirals</button><div id="spiral-md">Loading&hellip;</div>`;
  $(".back-btn", detail).addEventListener("click", () => {
    list.hidden = false;
    detail.hidden = true;
  });
  try {
    const md = await fetchText(`${ROOT}spirals/${handle}/spiral.md`);
    renderMarkdown($("#spiral-md", detail), md);
  } catch (e) {
    showError($("#spiral-md", detail), escapeHtml(String(e.message || e)));
  }
}

function setupTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const view = tab.dataset.view;
      $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      $$(".view").forEach((v) =>
        v.classList.toggle("active", v.id === `view-${view}`)
      );
    });
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function init() {
  setupTabs();
  await Promise.all([loadConstitution(), loadJoining(), loadSpirals()]);
}

init();
