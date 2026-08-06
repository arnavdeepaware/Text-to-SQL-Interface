const form = document.querySelector("#query-form");
const questionInput = document.querySelector("#question");
const sampleButton = document.querySelector("#sample-button");
const schemaEl = document.querySelector("#schema");
const sqlEl = document.querySelector("#sql");
const confidenceEl = document.querySelector("#confidence");
const rationaleEl = document.querySelector("#rationale");
const errorEl = document.querySelector("#error");
const resultsEl = document.querySelector("#results");

const sampleQuestions = [
  "Which customers generated the most revenue?",
  "What is total paid revenue?",
  "Show revenue by product",
  "List recent orders",
  "What tables are available?"
];

sampleButton.addEventListener("click", () => {
  const index = Math.floor(Math.random() * sampleQuestions.length);
  questionInput.value = sampleQuestions[index];
  questionInput.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runQuestion(questionInput.value);
});

async function runQuestion(question) {
  setLoading();
  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });
  const payload = await response.json();
  if (!response.ok) {
    showError(payload.error || "The query could not be generated.");
    return;
  }
  errorEl.hidden = true;
  sqlEl.textContent = payload.sql;
  confidenceEl.textContent = `${Math.round(payload.confidence * 100)}%`;
  rationaleEl.textContent = payload.rationale;
  renderTable(payload.columns, payload.rows);
}

function setLoading() {
  errorEl.hidden = true;
  sqlEl.textContent = "Generating SQL...";
  confidenceEl.textContent = "--";
  rationaleEl.textContent = "";
  resultsEl.innerHTML = "";
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
  sqlEl.textContent = "No SQL generated.";
  confidenceEl.textContent = "--";
  rationaleEl.textContent = "";
  resultsEl.innerHTML = "";
}

function renderTable(columns, rows) {
  if (!rows.length) {
    resultsEl.innerHTML = "<tbody><tr><td>No rows returned.</td></tr></tbody>";
    return;
  }

  const head = `<thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>`;
  const body = rows
    .map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>`)
    .join("");
  resultsEl.innerHTML = `${head}<tbody>${body}</tbody>`;
}

async function loadSchema() {
  const response = await fetch("/api/schema");
  const payload = await response.json();
  schemaEl.innerHTML = Object.entries(payload.schema)
    .map(([table, columns]) => {
      const columnText = columns.map((column) => `${column.name} ${column.type}`).join(", ");
      return `<div class="schema-table"><strong>${escapeHtml(table)}</strong><code>${escapeHtml(columnText)}</code></div>`;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadSchema();
