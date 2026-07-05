/**
 * Session-start architecture readiness check.
 *
 * 1. Verify CBM MCP is accessible (list_projects via child process)
 * 2. Check artifacts freshness (compare .last-refreshed with git HEAD)
 * 3. Read runtime evidence cache
 * 4. Inform agent about artifact state
 *
 * Called by .cursor/hooks.json "sessionStart" hook.
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execSync } = require("child_process");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-session-arch-checked.lock");
const RUNTIME_DIR = path.join(__dirname, "..", "..", "knowledge", "runtime");
const EVIDENCE_DIR = path.join(RUNTIME_DIR, "evidence");
const LAST_REFRESHED = path.join(RUNTIME_DIR, ".last-refreshed");
const WORKSPACE_ROOT = path.resolve(__dirname, "..", "..");
const MCP_CONFIG = path.join(WORKSPACE_ROOT, ".cursor", "mcp.json");

function readTimestamp(filepath) {
  try {
    return fs.readFileSync(filepath, "utf8").trim();
  } catch {
    return null;
  }
}

function checkArtifactsFreshness() {
  const lastRefreshed = readTimestamp(LAST_REFRESHED);
  if (!lastRefreshed) {
    return { status: "unknown", message: "Artefakty nigdy nie byly generowane." };
  }

  const refreshed = new Date(lastRefreshed);
  const now = new Date();
  const hoursSinceRefresh = (now - refreshed) / (1000 * 60 * 60);

  if (hoursSinceRefresh > 24) {
    return { status: "stale", message: `Artefakty sprzed ${Math.round(hoursSinceRefresh)}h — zbyt stare, wymagaja regeneracji.` };
  }
  return { status: "fresh", message: `Artefakty aktualne od: ${lastRefreshed.slice(0, 19)}` };
}

function countEvidenceFiles() {
  try {
    if (!fs.existsSync(EVIDENCE_DIR)) return 0;
    return fs.readdirSync(EVIDENCE_DIR).filter(f => f.endsWith(".json")).length;
  } catch {
    return 0;
  }
}

/**
 * Check which MCP servers are likely available by verifying their base commands.
 * Non-blocking: only checks if the command exists on PATH, doesn't start servers.
 */
function checkMCPHealth() {
  const results = [];
  const config = fs.existsSync(MCP_CONFIG) ? JSON.parse(fs.readFileSync(MCP_CONFIG, "utf8")) : null;
  if (!config || !config.mcpServers) {
    return ["  MCP config not found or empty."];
  }

  const servers = Object.entries(config.mcpServers);
  for (const [name, cfg] of servers) {
    const cmd = cfg.command || "";
    try {
      // Handle absolute paths (like serena.exe)
      if (path.isAbsolute(cmd)) {
        if (fs.existsSync(cmd)) {
          results.push(`  ${name}: ✅`);
        } else {
          results.push(`  ${name}: ⚠️  binary not found at "${cmd}"`);
        }
        continue;
      }
      // Check if the base command exists on PATH
      const whichCmd = process.platform === "win32" ? `where "${cmd}"` : `which "${cmd}"`;
      execSync(whichCmd, { timeout: 2000, stdio: "pipe" });
      results.push(`  ${name}: ✅`);
    } catch {
      // Try resolving via npx/uvx (those always "exist")
      if (cmd === "npx" || cmd === "uvx") {
        results.push(`  ${name}: ✅ (via ${cmd})`);
      } else {
        results.push(`  ${name}: ⚠️  "${cmd}" not on PATH`);
      }
    }
  }
  return results;
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
    const loopCount = Number(payload.loop_count || 0);

    // Sentinel lock: run only ONCE per Cursor process
    if (fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    if (loopCount === 0) {
      const freshness = checkArtifactsFreshness();
      const evidenceCount = countEvidenceFiles();
      const mcpHealth = checkMCPHealth();

      const msg = [
        "[ARCH CHECK] " + freshness.message + " " +
        `Evidence cache: ${evidenceCount} files.`,
        "",
        "--- MCP STATUS ---",
        ...mcpHealth,
        "",
        freshness.status === "stale"
          ? "Run node .cursor/hooks/generate-runtime-artifacts.js to refresh."
          : "System ready.",
      ].join("\n");

      process.stdout.write(
        JSON.stringify({
          followup_message: msg,
        }) + "\n",
      );
      // Write sentinel lock
      try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }
      return;
    }
    process.stdout.write("{}\n");
  } catch {
    process.stdout.write("{}\n");
  }
});
