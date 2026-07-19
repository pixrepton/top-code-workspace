/**
 * Session-stop drift snapshot.
 *
 * This hook does not commit and does not write a persistent repo memory bank.
 * It writes a small operational snapshot to TOP_CODE_SESSION_SCRATCH or
 * C:\top-code-session-scratch for the current operator session only.
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const {
  SESSION_SCRATCH_ROOT,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const WORKSPACE_ROOT = path.join(__dirname, "..", "..");
const DRIFT_LOG = path.join(SESSION_SCRATCH_ROOT, "SESSION_DRIFT.md");

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function gitLines(args) {
  try {
    const out = execSync(`git ${args}`, {
      encoding: "utf8",
      cwd: WORKSPACE_ROOT,
      timeout: 5000,
    });
    return out.split(/\r?\n/).filter(Boolean);
  } catch {
    return [];
  }
}

function isRelevant(fp) {
  return /\.(py|js|ts|php|sql|ya?ml|json|md|mdc|ps1|sh|html|css)$/.test(fp);
}

function classifyFile(fp) {
  if (fp.startsWith("gmail-agent/")) return "gmail-agent";
  if (fp.startsWith("daszek/")) return "daszek";
  if (fp.startsWith("kalk-top/")) return "kalk-top";
  if (fp.startsWith("knowledge/")) return "knowledge";
  if (fp.startsWith(".cursor/")) return ".cursor";
  if (fp.startsWith("scripts/")) return "scripts";
  return "other";
}

function runArchRefresh() {
  ensureDir(SESSION_SCRATCH_ROOT);

  const changed = gitLines("diff --name-only HEAD").filter(isRelevant);
  const untracked = gitLines("ls-files --others --exclude-standard").filter(isRelevant);
  const byArea = {};
  for (const fp of [...changed, ...untracked]) {
    const area = classifyFile(fp);
    if (!byArea[area]) byArea[area] = [];
    byArea[area].push(fp);
  }

  const total = changed.length + untracked.length;
  const lines = [
    "# Session drift snapshot",
    "",
    `Generated: ${new Date().toISOString()}`,
    `Workspace: ${WORKSPACE_ROOT}`,
    `Changed files: ${changed.length}`,
    `Untracked files: ${untracked.length}`,
    "",
    "## Areas",
    "",
  ];

  for (const [area, files] of Object.entries(byArea).sort((a, b) => b[1].length - a[1].length)) {
    lines.push(`- ${area}: ${files.length}`);
  }

  lines.push("", "## Modified", "");
  for (const fp of changed) lines.push(`- \`${fp}\``);
  lines.push("", "## Untracked", "");
  for (const fp of untracked) lines.push(`- \`${fp}\``);
  lines.push("");

  fs.writeFileSync(DRIFT_LOG, lines.join("\n"), "utf8");
  writeCloseoutLog(WORKSPACE_ROOT, [
    "[arch-refresh] OK",
    `  ${total} relevant files drifted`,
    `  scratch: ${DRIFT_LOG}`,
  ]);
}

readStdinPayload().then((payload) => {
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId || "unknown";

    if (!acquireSessionEndLock(`arch-refresh-${convoId}`, manual)) {
      process.stdout.write("{}\n");
      return;
    }

    runArchRefresh();
    process.stdout.write("{}\n");
  } catch (err) {
    try { writeCloseoutLog(WORKSPACE_ROOT, [`[arch-refresh] ERROR: ${err.message}`]); } catch { /* noop */ }
    process.stdout.write("{}\n");
  }
});
