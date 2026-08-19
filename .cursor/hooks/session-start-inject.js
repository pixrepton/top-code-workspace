/**
 * Session-start context injector (auto + manual).
 *
 * Reads canonical workspace memory live from knowledge/memory/.
 * Also reports active AI-OS tasks and GitNexus index staleness hints.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { execSync } = require("child_process");

const root = process.env.TOP_CODE_ROOT || path.resolve(__dirname, "../..");
const memoryRoot = path.join(root, "knowledge", "memory");

const NESTED_REPOS = [
  "gmail-agent",
  "kalk-top",
  "daszek",
  "rag-chat-asystent",
  "rag-widget",
  "cieplo-orchestrator",
  "top-instal-generator",
  "fast-kalk",
  "knowledge",
];

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

function tasksActiveDir() {
  const explicit = process.env.AI_OS_TASK_STATE_DIR;
  if (explicit) {
    return path.join(explicit, "tasks", "active");
  }
  const scratch =
    process.env.TOP_CODE_SESSION_SCRATCH ||
    (process.platform === "win32" ? "C:\\top-code-session-scratch" : path.join(os.homedir(), "top-code-session-scratch"));
  return path.join(scratch, "ai-os-execution", "top-code-workspace", "tasks", "active");
}

function formatActiveTasks() {
  const dir = tasksActiveDir();
  if (!fs.existsSync(dir)) {
    return "ACTIVE TASKS: UNKNOWN (tasks/active directory not found; set TOP_CODE_SESSION_SCRATCH or AI_OS_TASK_STATE_DIR)";
  }
  try {
    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
    if (!files.length) {
      return "ACTIVE TASKS: none";
    }
    const lines = [];
    for (const file of files) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
        const next = String(data.next_action || "").slice(0, 120);
        lines.push(
          `- ${data.task_id || file}: [${data.status || "?"}] phase=${data.current_phase || "?"} updated=${(data.updated_at_utc || "").slice(0, 19)} next=${next}`
        );
      } catch {
        lines.push(`- ${file}: (unreadable checkpoint JSON)`);
      }
    }
    return lines.join("\n");
  } catch {
    return "ACTIVE TASKS: UNKNOWN (failed to read tasks/active)";
  }
}

function gitHeadIso(repoDir) {
  try {
    return execSync("git log -1 --format=%cI", {
      cwd: repoDir,
      encoding: "utf8",
      timeout: 5000,
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

function cbmCacheDir() {
  const explicit = process.env.CBM_CACHE_DIR;
  if (explicit) return explicit.replace(/\\/g, "/");
  if (process.platform === "win32") return "C:/ai-os-codebase-memory";
  return path.join(os.homedir(), ".cache", "codebase-memory-mcp");
}

function cbmProjectId(repo) {
  const rootEncoded = "C-Users-compg-Desktop-top-code-workspace";
  if (repo === "workspace") return "top-code-workspace";
  return `${rootEncoded}-${repo}`;
}

function cbmIndexedIso(projectId) {
  const dbPath = path.join(cbmCacheDir().replace(/\//g, path.sep), `${projectId}.db`);
  if (!fs.existsSync(dbPath)) return null;
  try {
    return new Date(fs.statSync(dbPath).mtimeMs).toISOString();
  } catch {
    return null;
  }
}

function formatCbmStaleness() {
  const lines = [];
  const workspaceIds = ["top-code-workspace", "C-Users-compg-Desktop-top-code-workspace"];
  const workspaceIndexed = workspaceIds.map((id) => cbmIndexedIso(id)).filter(Boolean);
  const head = gitHeadIso(root) || "?";
  if (workspaceIndexed.length) {
    const latest = workspaceIndexed.sort().reverse()[0];
    const stale = latest && head && latest < head ? "STALE" : "check";
    lines.push(`- workspace shell: indexed=${latest} head=${head} (${stale})`);
  } else {
    lines.push("- workspace shell: no CBM .db in cache");
  }
  for (const repo of NESTED_REPOS) {
    const indexedAt = cbmIndexedIso(cbmProjectId(repo));
    const headRepo = gitHeadIso(path.join(root, repo)) || "?";
    if (!indexedAt) {
      lines.push(`- ${repo}: no CBM .db`);
      continue;
    }
    const stale = indexedAt && headRepo && indexedAt < headRepo ? "STALE" : "check";
    lines.push(`- ${repo}: indexed=${indexedAt} head=${headRepo} (${stale})`);
  }
  return lines.join("\n");
}

function formatCodeIntelStaleness() {
  const lines = [];
  const rootMeta = path.join(root, ".gitnexus", "meta.json");
  if (fs.existsSync(rootMeta)) {
    try {
      const meta = JSON.parse(fs.readFileSync(rootMeta, "utf8"));
      const indexedAt = meta.indexedAt || meta.generatedAt || "?";
      const head = gitHeadIso(root) || "?";
      lines.push(`- workspace shell: indexed=${indexedAt} head=${head}`);
    } catch {
      lines.push("- workspace shell: meta unreadable");
    }
  }
  for (const repo of NESTED_REPOS) {
    const repoDir = path.join(root, repo);
    const metaPath = path.join(repoDir, ".gitnexus", "meta.json");
    if (!fs.existsSync(metaPath)) {
      lines.push(`- ${repo}: no .gitnexus index`);
      continue;
    }
    try {
      const meta = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      const indexedAt = meta.indexedAt || meta.generatedAt || "?";
      const head = gitHeadIso(repoDir) || "?";
      const stale = indexedAt && head && indexedAt < head ? "STALE" : "check";
      lines.push(`- ${repo}: indexed=${indexedAt} head=${head} (${stale})`);
    } catch {
      lines.push(`- ${repo}: meta unreadable`);
    }
  }
  return lines.join("\n");
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
    if (payload.loop_count > 0) {
      process.stdout.write("{}\n");
      return;
    }

    const parts = [
      "TOP-INSTAL session context (memory read live from repo; scratch SESSION_START_CONTEXT.md is not SoT):\n",
    ];

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

    parts.push(`\n--- ACTIVE TASKS ---\n${formatActiveTasks()}`);
    parts.push(`\n--- CODE-INTEL STALENESS (local .gitnexus meta vs git HEAD) ---\n${formatCodeIntelStaleness()}`);
    parts.push(`\n--- CBM STALENESS (${cbmCacheDir()} .db mtime vs git HEAD) ---\n${formatCbmStaleness()}`);

    parts.push(
      "\nMemory SoT: knowledge/memory/{OPERATOR_DECISIONS,BACKLOG,ACTIVE_WORKSPACE,LAST_SESSION}.md. " +
      "Do not create persistent transcript/reflection stores."
    );

    process.stdout.write(JSON.stringify({ followup_message: parts.join("\n") }) + "\n");
  } catch {
    process.stdout.write("{}\n");
  }
});
