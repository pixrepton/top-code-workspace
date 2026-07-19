/**
 * Manual session-start context injector.
 *
 * Reads only the canonical workspace memory files:
 * - knowledge/memory/OPERATOR_DECISIONS.md
 * - knowledge/memory/BACKLOG.md
 * - knowledge/memory/ACTIVE_WORKSPACE.md
 * - knowledge/memory/LAST_SESSION.md
 *
 * Generated session context is written by scripts/run-session-start-hooks.ps1
 * to TOP_CODE_SESSION_SCRATCH or C:\top-code-session-scratch, outside the repo.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-session-start-injected.lock");
const root = process.env.TOP_CODE_ROOT || path.resolve(__dirname, "../..");
const memoryRoot = path.join(root, "knowledge", "memory");

function readTrimmed(fp, maxChars, transform) {
  if (!fs.existsSync(fp)) return null;
  try {
    let text = fs.readFileSync(fp, "utf8");
    if (transform) text = transform(text);
    if (!text) return null;
    if (text.length > maxChars) return `${text.slice(0, maxChars)}\n...[truncated]`;
    return text;
  } catch {
    return null;
  }
}

function extractActiveSections(text) {
  const lines = text.split(/\r?\n/);
  const sections = [];
  let current = null;

  for (const line of lines) {
    if (/^## \[ACTIVE\]/.test(line)) {
      if (current) sections.push(current);
      current = [line];
      continue;
    }
    if (/^## \[(SUPERSEDED|FUTURE)\]/.test(line)) {
      if (current) sections.push(current);
      current = null;
      continue;
    }
    if (current) current.push(line);
  }

  if (current) sections.push(current);
  return sections.map((s) => s.join("\n").trim()).filter(Boolean).join("\n\n");
}

function readJsonStdin(callback) {
  const chunks = [];
  process.stdin.on("data", (c) => chunks.push(c));
  process.stdin.on("end", () => {
    try {
      const raw = (Buffer.concat(chunks).toString("utf8") || "{}").trim();
      callback(JSON.parse(raw || "{}"));
    } catch {
      callback({});
    }
  });
}

readJsonStdin((payload) => {
  try {
    const manual = Boolean(payload.manual);
    if (payload.loop_count > 0) {
      process.stdout.write("{}\n");
      return;
    }

    if (!manual && fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    const parts = ["TOP-INSTAL session context (canonical memory only):\n"];

    const activeDecisions = readTrimmed(
      path.join(memoryRoot, "OPERATOR_DECISIONS.md"),
      7000,
      extractActiveSections
    );
    if (activeDecisions) {
      parts.push(`\n--- OPERATOR_DECISIONS [ACTIVE] ---\n${activeDecisions}`);
    }

    const backlog = readTrimmed(path.join(memoryRoot, "BACKLOG.md"), 2500);
    if (backlog) parts.push(`\n--- BACKLOG ---\n${backlog}`);

    const activeWorkspace = readTrimmed(path.join(memoryRoot, "ACTIVE_WORKSPACE.md"), 2500);
    if (activeWorkspace) parts.push(`\n--- ACTIVE_WORKSPACE ---\n${activeWorkspace}`);

    const lastSession = readTrimmed(path.join(memoryRoot, "LAST_SESSION.md"), 2000);
    if (lastSession) parts.push(`\n--- LAST_SESSION ---\n${lastSession}`);

    parts.push(
      "\nMemory SoT: knowledge/memory/{OPERATOR_DECISIONS,BACKLOG,ACTIVE_WORKSPACE,LAST_SESSION}.md. " +
      "Session scratch is outside repo; do not create persistent transcript/reflection stores."
    );

    process.stdout.write(JSON.stringify({ followup_message: parts.join("\n") }) + "\n");
    if (!manual) {
      try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { /* best-effort */ }
    }
  } catch {
    process.stdout.write("{}\n");
  }
});
