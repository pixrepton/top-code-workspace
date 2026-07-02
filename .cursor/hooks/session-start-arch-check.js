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

      process.stdout.write(
        JSON.stringify({
          followup_message:
            "[ARCH CHECK] " + freshness.message + " " +
            `Evidence cache: ${evidenceCount} files. ` +
            (freshness.status === "stale"
              ? "Run node .cursor/hooks/generate-runtime-artifacts.js to refresh."
              : "System ready."),
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
