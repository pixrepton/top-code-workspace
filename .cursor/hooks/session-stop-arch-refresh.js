/**
 * Session-stop architecture refresh hook.
 *
 * WHAT THIS DOES:
 *   1. Checks git diff for changed files since HEAD
 *   2. If relevant files changed, creates a drift snapshot in top-code-memory/
 *   3. Writes a .last-refreshed timestamp for freshness tracking
 *   4. Outputs a summary of what drifted
 *
 * ACTIVATION:
 *   Called by Cursor IDE via .cursor/hooks.json "stop" hook.
 *   Receives stdin JSON: { status: "completed", loop_count: 0 }
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const WORKSPACE_ROOT = path.join(__dirname, "..", "..");
const MEMORY_DIR = path.join(WORKSPACE_ROOT, "top-code-memory");
const LAST_REFRESHED = path.join(MEMORY_DIR, ".last-refreshed");
const DRIFT_LOG = path.join(MEMORY_DIR, "DRIFT.md");

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function getGitDiff() {
  try {
    const result = execSync('git diff --name-only HEAD', {
      encoding: 'utf8',
      cwd: WORKSPACE_ROOT,
      timeout: 5000,
    });
    return result.split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function getUntracked() {
  try {
    const result = execSync('git ls-files --others --exclude-standard', {
      encoding: 'utf8',
      cwd: WORKSPACE_ROOT,
      timeout: 5000,
    });
    return result.split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function classifyFile(fp) {
  if (fp.startsWith("gmail-agent/")) return "gmail-agent";
  if (fp.startsWith("rag-chat-asystent/")) return "rag-chat-asystent";
  if (fp.startsWith("daszek/")) return "daszek";
  if (fp.startsWith("rag-widget/")) return "rag-widget";
  if (fp.startsWith("top-code-memory/")) return "top-code-memory";
  if (fp.startsWith("knowledge/")) return "knowledge";
  if (fp.startsWith("scripts/")) return "scripts";
  if (fp.startsWith(".cursor/")) return ".cursor";
  if (fp.startsWith("top-instal-generator/")) return "top-instal-generator";
  if (fp.startsWith("fast-kalk/")) return "fast-kalk";
  if (fp.startsWith("kalk-top/")) return "kalk-top";
  if (fp.startsWith("cieplo-orchestrator/")) return "cieplo-orchestrator";
  return "other";
}

function relevantExtensions() {
  return [".py", ".js", ".yml", ".yaml", ".env", ".sql", ".php", ".md", ".json", ".mdc", ".html", ".sh", ".ps1"];
}

function isRelevant(fp) {
  return relevantExtensions().some(ext => fp.endsWith(ext));
}

function writeTimestamp() {
  ensureDir(MEMORY_DIR);
  fs.writeFileSync(LAST_REFRESHED, new Date().toISOString(), "utf8");
}

function updateDriftLog(changedFiles, untrackedFiles, summary) {
  ensureDir(MEMORY_DIR);

  const header = "# Drift Log\n\n> Auto-generated at session end. Lists all files changed during the session.\n\n";
  const date = new Date().toISOString().split("T")[0];

  let entries = [`## ${date}`, "", summary, "", "### Modified", ""];
  for (const f of changedFiles) {
    entries.push(`- \`${f}\``);
  }
  entries.push("", "### Untracked (new)", "");
  for (const f of untrackedFiles) {
    entries.push(`- \`${f}\``);
  }
  entries.push("", "---", "");

  const newSection = entries.join("\n") + "\n";

  // If the log exists and already has an entry for today, replace it
  const existing = fs.existsSync(DRIFT_LOG) ? fs.readFileSync(DRIFT_LOG, "utf8") : header;
  const todayMarker = `## ${date}`;
  if (existing.includes(todayMarker)) {
    // Replace everything between today's ## and the next ## or end
    const regex = new RegExp(`${todayMarker}[\\s\\S]*?(?=\\n## |\\n---|$)`, 'm');
    const updated = existing.replace(regex, newSection.trimEnd());
    fs.writeFileSync(DRIFT_LOG, updated, "utf8");
  } else {
    // Append to top (after header)
    const body = existing.replace(header, "");
    const content = header + newSection + "\n" + body;
    fs.writeFileSync(DRIFT_LOG, content, "utf8");
  }
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    const changedFiles = getGitDiff();
    const untrackedFiles = getUntracked();

    // Filter to relevant extensions and files
    const relevantChanged = changedFiles.filter(isRelevant);
    const relevantUntracked = untrackedFiles.filter(f => isRelevant(f) && !f.includes("__pycache__") && !f.includes("model_cache") && !f.includes(".pyc"));

    // Classify by area
    const byArea = {};
    for (const f of [...relevantChanged, ...relevantUntracked]) {
      const area = classifyFile(f);
      if (!byArea[area]) byArea[area] = [];
      byArea[area].push(f);
    }

    // Build summary
    const totalChanges = relevantChanged.length + relevantUntracked.length;
    let summary = `**${totalChanges} files changed** across ${Object.keys(byArea).length} areas.`;
    if (totalChanges > 0) {
      const areas = Object.entries(byArea)
        .sort((a, b) => b[1].length - a[1].length)
        .map(([area, files]) => `  ${area}: ${files.length} files`);
      summary += "\n" + areas.join("\n");
    }

    // Save drift log if there were changes
    if (totalChanges > 0) {
      updateDriftLog(relevantChanged, relevantUntracked, summary);
    }

    writeTimestamp();

    // Output
    const lines = ["🏗️  ARCHITECTURE REFRESH", ""];
    if (totalChanges === 0) {
      lines.push("  No drift detected — all clean.");
    } else {
      lines.push(`  ${totalChanges} files drifted:`);
      const sortedAreas = Object.entries(byArea).sort((a, b) => b[1].length - a[1].length);
      for (const [area, files] of sortedAreas) {
        lines.push(`    ${area}: ${files.length} files`);
      }
      lines.push("");
      lines.push(`  Full log: top-code-memory/DRIFT.md`);
    }
    lines.push(`  Last refreshed: ${new Date().toISOString().slice(0, 19)}`);

    process.stdout.write(JSON.stringify({ followup_message: lines.join("\n") }) + "\n");
  } catch (err) {
    process.stdout.write(JSON.stringify({ followup_message: `[arch refresh error] ${err.message}` }) + "\n");
  }
});
