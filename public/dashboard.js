const POLL_MS = 12000;
let pollTimer = null;

const GENDER_COLS = [
  { code: "1", label: "Male" },
  { code: "2", label: "Female" },
];

const AGE_COLS = [
  { code: "1", label: "<25", title: "Less than 25 years old" },
  { code: "2", label: "25–35", title: "25–35 years old" },
  { code: "3", label: "36–45", title: "36–45 years old" },
  { code: "4", label: "46–55", title: "46–55 years old" },
  { code: "5", label: "56–65", title: "56–65 years old" },
  { code: "6", label: "65+", title: "65 years and older" },
];

function fmtTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function lookup(rows, code) {
  return (rows || []).find((row) => row.code === code) || { count: 0, pct: 0 };
}

function unanswered(rows) {
  return (rows || []).find((row) => row.code == null) || { count: 0, pct: 0 };
}

function metricCell(row, kind) {
  const count = row.count || 0;
  const pct = row.pct || 0;
  const empty = count === 0 ? " is-empty" : "";
  return `<td class="metric ${kind}${empty}" style="--p:${pct}%">
    <span class="n">${count}</span>
    <span class="p">${pct}%</span>
  </td>`;
}

function armCells(arm) {
  const gender = GENDER_COLS.map((col) => metricCell(lookup(arm.gender, col.code), "gender")).join("");
  const age = AGE_COLS.map((col) => metricCell(lookup(arm.age, col.code), "age")).join("");
  return gender + age;
}

function categoryHeads() {
  const gender = GENDER_COLS.map((col) => `<th class="leaf gender">${esc(col.label)}</th>`).join("");
  const age = AGE_COLS.map(
    (col) => `<th class="leaf age" title="${esc(col.title)}">${esc(col.label)}</th>`
  ).join("");
  return gender + age;
}

function armNote(arm) {
  const missing = Math.max(unanswered(arm.gender).count, unanswered(arm.age).count);
  if (!arm.submissions) return "No rows yet";
  if (!missing) return `${arm.submissions} rows`;
  return `${arm.submissions} rows · ${missing} not asked`;
}

function renderSurveyTable(survey) {
  const genderSpan = GENDER_COLS.length;
  const ageSpan = AGE_COLS.length;
  const armSpan = genderSpan + ageSpan;
  return `
    <article class="sheet">
      <header class="sheet-head">
        <span class="survey-mark">${esc(survey.brand)}</span>
        <h3>Fragrance Survey</h3>
      </header>
      <div class="sheet-scroll">
        <table>
          <colgroup class="control" span="${armSpan}"></colgroup>
          <colgroup class="experimental" span="${armSpan}"></colgroup>
          <thead>
            <tr class="arm-row">
              <th class="control" colspan="${armSpan}">
                <em>Control (1)</em>
                <span>${esc(armNote(survey.control))}</span>
              </th>
              <th class="experimental" colspan="${armSpan}">
                <em>Experimental (2)</em>
                <span>${esc(armNote(survey.experimental))}</span>
              </th>
            </tr>
            <tr class="group-row">
              <th class="control gender" colspan="${genderSpan}">Gender</th>
              <th class="control age" colspan="${ageSpan}">Age</th>
              <th class="experimental gender" colspan="${genderSpan}">Gender</th>
              <th class="experimental age" colspan="${ageSpan}">Age</th>
            </tr>
            <tr class="leaf-row">
              ${categoryHeads()}
              ${categoryHeads()}
            </tr>
          </thead>
          <tbody>
            <tr>
              ${armCells(survey.control)}
              ${armCells(survey.experimental)}
            </tr>
          </tbody>
        </table>
      </div>
    </article>`;
}

function renderSurveys(surveys) {
  const root = document.getElementById("surveys");
  if (!surveys.length) {
    root.innerHTML = `<article class="sheet"><p class="empty">No tagged surveys yet.</p></article>`;
    return;
  }
  root.innerHTML = surveys.map(renderSurveyTable).join("");
}

function renderMeta(data) {
  const live = data.source === "kobo" && !data.stale;
  const source = live ? "Live from Kobo" : "Showing last known data";
  const extra = data.error ? ` · ${data.error}` : "";
  document.getElementById("generated").textContent =
    `${source} · ${data.submissions} rows · ${data.control_n} control · ${data.experimental_n} experimental · last ${fmtTime(data.last_submission)}${extra}`;
}

async function load({ refresh = false, silent = false } = {}) {
  const params = new URLSearchParams();
  if (refresh) params.set("refresh", "1");
  if (!silent) {
    document.getElementById("generated").textContent = refresh
      ? "Fetching live Kobo data…"
      : "Loading…";
  }
  try {
    const query = params.toString();
    const response = await fetch(`/api/dashboard${query ? `?${query}` : ""}`);
    if (!response.ok) {
      document.getElementById("generated").textContent = "Could not load Kobo data.";
      return;
    }
    const data = await response.json();
    renderMeta(data);
    renderSurveys(data.surveys || []);
  } catch {
    document.getElementById("generated").textContent = "Could not load Kobo data.";
  }
}

function schedulePoll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    load({ silent: true });
  }, POLL_MS);
}

document.getElementById("reload").addEventListener("click", () => {
  load({ refresh: true }).then(schedulePoll);
});
load().then(schedulePoll);
