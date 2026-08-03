/**
 * Session-stop multi-repo drift snapshot.
 *
 * Does not commit and does not write persistent repo memory.
 * Writes scratch-only artifacts under TOP_CODE_SESSION_SCRATCH.
 */

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const {
  SESSION_SCRATCH_ROOT,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const WORKSPACE_ROOT = path.join(__dirname, "..", "..");
const DRIFT_LOG = path.join(SESSION_SCRATCH_ROOT, "SESSION_DRIFT.md");
const REPOS_LOCK = path.join(WORKSPACE_ROOT, "workspace-repos.lock.json");

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function discoverRepositories() {
  const repos = [
    {
      id: "workspace",
      relPath: ".",
      label: "workspace (root meta-repo)",
    },
  ];
  try {
    const lock = JSON.parse(fs.readFileSync(REPOS_LOCK, "utf8"));
    for (const entry of lock.repos || []) {
      if (entry.type !== "git_repo" || !entry.exists || !entry.path) continue;
      repos.push({
        id: String(entry.path).replace(/\\/g, "/"),
        relPath: entry.path,
        label: String(entry.path),
      });
    }
  } catch (err) {
    repos[0].discoveryWarning = `workspace-repos.lock.json unreadable: ${err.message}`;
  }
  const seen = new Set();
  return repos.filter((repo) => {
    const key = repo.relPath;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function gitInRepo(repoPath, args) {
  const proc = spawnSync("git", args, {
    encoding: "utf8",
    cwd: repoPath,
    timeout: 8000,
  });
  if (proc.error) throw proc.error;
  if (proc.status !== 0) {
    const detail = (proc.stderr || proc.stdout || `git ${args.join(" ")} failed`).trim();
    const err = new Error(detail);
    err.stderr = proc.stderr;
    throw err;
  }
  return (proc.stdout || "").trim();
}

function inspectRepository(repo) {
  const absPath = path.resolve(WORKSPACE_ROOT, repo.relPath);
  const simulate = process.env.SESSION_STOP_SIMULATE_ERROR_REPO;
  if (simulate && (repo.id === simulate || repo.relPath === simulate)) {
    return {
      ...repo,
      absPath,
      state: "ERROR",
      error: "simulated repository inspection failure",
    };
  }
  if (!fs.existsSync(absPath)) {
    return { ...repo, absPath, state: "NOT_REPO", error: "path does not exist" };
  }
  if (!fs.existsSync(path.join(absPath, ".git"))) {
    return { ...repo, absPath, state: "NOT_REPO", error: "missing .git directory" };
  }
  try {
    const branch = gitInRepo(absPath, ["branch", "--show-current"]) || "(detached)";
    const head = gitInRepo(absPath, ["rev-parse", "--short", "HEAD"]);
    const shortStatus = gitInRepo(absPath, ["status", "--short"]);
    return {
      ...repo,
      absPath,
      state: shortStatus ? "DIRTY" : "OK",
      branch,
      head,
      shortStatus,
    };
  } catch (err) {
    const detail = (err.stderr || err.message || String(err)).trim();
    return { ...repo, absPath, state: "ERROR", error: detail };
  }
}

function formatStatusBlock(repo) {
  const lines = [
    `### ${repo.label}`,
    "",
    `- state: **${repo.state}**`,
  ];
  if (repo.branch) lines.push(`- branch: \`${repo.branch}\``);
  if (repo.head) lines.push(`- head: \`${repo.head}\``);
  if (repo.error) lines.push(`- error: ${repo.error}`);
  lines.push("", "```text");
  lines.push(repo.shortStatus || "(clean)");
  lines.push("```", "");
  return lines;
}

function runArchRefresh() {
  ensureDir(SESSION_SCRATCH_ROOT);
  const warnings = [];
  const repos = discoverRepositories();
  if (repos[0]?.discoveryWarning) warnings.push(repos[0].discoveryWarning);

  const inspected = repos.map((repo) => inspectRepository(repo));
  for (const repo of inspected) {
    if (repo.state === "ERROR") {
      warnings.push(`${repo.label}: ${repo.error}`);
    }
  }

  const summary = {
    OK: inspected.filter((r) => r.state === "OK").length,
    DIRTY: inspected.filter((r) => r.state === "DIRTY").length,
    ERROR: inspected.filter((r) => r.state === "ERROR").length,
    NOT_REPO: inspected.filter((r) => r.state === "NOT_REPO").length,
  };

  const lines = [
    "# Session drift snapshot",
    "",
    `Generated: ${new Date().toISOString()}`,
    `Workspace: ${WORKSPACE_ROOT}`,
    `Repositories scanned: ${inspected.length}`,
    "",
    "## Summary",
    "",
    `- OK: ${summary.OK}`,
    `- DIRTY: ${summary.DIRTY}`,
    `- ERROR: ${summary.ERROR}`,
    `- NOT_REPO: ${summary.NOT_REPO}`,
    "",
    "## Repository status",
    "",
    "| Repository | State | Branch | HEAD |",
    "| --- | --- | --- | --- |",
  ];

  for (const repo of inspected) {
    const branch = repo.branch ? repo.branch.replace(/\|/g, "\\|") : "-";
    const head = repo.head || "-";
    lines.push(`| ${repo.label} | ${repo.state} | ${branch} | ${head} |`);
  }

  lines.push("", "## Details", "");
  for (const repo of inspected) {
    lines.push(...formatStatusBlock(repo));
  }

  fs.writeFileSync(DRIFT_LOG, lines.join("\n"), "utf8");

  const closeoutLines = [
    "[arch-refresh] " + (warnings.length ? "WARN" : "OK"),
    `  repos=${inspected.length} ok=${summary.OK} dirty=${summary.DIRTY} error=${summary.ERROR} not_repo=${summary.NOT_REPO}`,
    `  scratch: ${DRIFT_LOG}`,
  ];
  for (const warning of warnings) closeoutLines.push(`  warning: ${warning}`);
  writeCloseoutLog(WORKSPACE_ROOT, closeoutLines);

  return { warnings, driftPath: DRIFT_LOG, inspected, summary };
}

readStdinPayload().then((payload) => {
  const response = { ok: true, warnings: [] };
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId || "unknown";

    if (!acquireSessionEndLock(`arch-refresh-${convoId}`, manual)) {
      response.ok = true;
      response.warnings = ["session-end lock already held; skipped duplicate arch-refresh"];
      process.stdout.write(`${JSON.stringify(response)}\n`);
      return;
    }

    const result = runArchRefresh();
    response.ok = result.warnings.length === 0;
    response.warnings = result.warnings;
    process.stdout.write(`${JSON.stringify(response)}\n`);
  } catch (err) {
    response.ok = false;
    response.warnings = [`arch-refresh failed: ${err.message}`];
    try {
      writeCloseoutLog(WORKSPACE_ROOT, [`[arch-refresh] ERROR: ${err.message}`]);
    } catch {
      /* noop */
    }
    process.stdout.write(`${JSON.stringify(response)}\n`);
  }
});

module.exports = {
  discoverRepositories,
  inspectRepository,
  runArchRefresh,
  DRIFT_LOG,
  WORKSPACE_ROOT,
};
