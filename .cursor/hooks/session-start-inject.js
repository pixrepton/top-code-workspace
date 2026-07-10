/**
 * Session-start context injector V2.
 *
 * Memory Retrieval Hierarchy:
 *   L1 = Current conversation context (automatic)
 *   L2 = Last Reflection (injected here, ~3000 chars)
 *   L3 = Older Reflections (lazy-load: agent reads from reflections/ when needed)
 *   L4 = Project docs (knowledge/, AGENTS.md, INDEX.md)
 *   L5 = RAG / openmemory MCP
 *
 * Sources injected:
 *   1. top-code-memory/reflections/INDEX.md  → latest Reflection (L2)
 *   2. knowledge/memory/OPERATOR_DECISIONS.md → active decisions
 *   3. knowledge/memory/BACKLOG.md            → open tasks
 *   4. top-code-memory/DRIFT.md               → what changed last session
 *   5. knowledge/memory/LAST_SESSION.md (always when present)
 *   6. Fallback: top-code-memory/LAST_SESSION.md (legacy)
 *
 * Manual activation: scripts/run-session-start-hooks.ps1
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-session-start-injected.lock");
const root = process.env.TOP_CODE_ROOT || path.resolve(__dirname, "../..");
const REFLECTIONS_DIR = path.join(root, "top-code-memory", "reflections");

function readTrimmed(fp, maxChars, transform) {
  if (!fs.existsSync(fp)) return null;
  try {
    let text = fs.readFileSync(fp, "utf8");
    if (transform) text = transform(text);
    if (text.length > maxChars) return text.slice(0, maxChars) + "\n...[truncated]";
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
    } else if (/^## \[(SUPERSEDED|FUTURE)\]/.test(line)) {
      if (current) { sections.push(current); current = null; }
    } else if (current) {
      current.push(line);
    }
  }
  if (current) sections.push(current);
  return sections.map((s) => s.join("\n").trim()).filter(Boolean).join("\n\n");
}

/**
 * Read the latest Reflection file by checking reflections/INDEX.md
 * and finding the most recent entry.
 */
function getLatestReflection() {
  const indexPath = path.join(REFLECTIONS_DIR, "INDEX.md");
  if (!fs.existsSync(indexPath)) return null;

  try {
    const index = fs.readFileSync(indexPath, "utf8");
    // Parse table rows: | 2026-07-01-slug | Topic | file.md |
    const rows = index.match(/\|\s*(\d{4}-\d{2}-\d{2}[^\s|]*)\s*\|/g);
    if (!rows || rows.length === 0) return null;

    // Get the last row (most recent)
    const lastRow = rows[rows.length - 1];
    const slugMatch = lastRow.match(/(\d{4}-\d{2}-\d{2}[^\s|]+)/);
    if (!slugMatch) return null;

    const slug = slugMatch[1];
    const reflPath = path.join(REFLECTIONS_DIR, slug + ".md");
    if (!fs.existsSync(reflPath)) return null;

    return readTrimmed(reflPath, 3000);
  } catch {
    return null;
  }
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse((Buffer.concat(chunks).toString("utf8") || "{}").trim());
    const manual = Boolean(payload.manual);
    if (payload.loop_count > 0) {
      process.stdout.write("{}\n");
      return;
    }

    if (!manual && fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    const parts = ["TOP-INSTAL session context (auto-injected):\n"];
    let hasReflection = false;

    // 1. L2: Latest Reflection (new primary memory system)
    const latestReflection = getLatestReflection();
    if (latestReflection) {
      hasReflection = true;
      parts.push(`\n--- REFLECTION (last session decisions) ---\n${latestReflection}`);
    }

    // 2. L3 hint: older reflections available
    if (hasReflection && fs.existsSync(REFLECTIONS_DIR)) {
      parts.push(
        "\n--- MEMORY RETRIEVAL ---\n" +
        "L2 loaded: last Reflection above.\n" +
        "L3 available: top-code-memory/reflections/ — read older reflections when you need historical context.\n" +
        "L4: knowledge/INDEX.md, AGENTS.md for project docs.\n" +
        "L5: openmemory MCP for deep memory search."
      );
    }

    // 3. OPERATOR_DECISIONS.md (active decisions)
    const activeDecisions = readTrimmed(
      path.join(root, "knowledge/memory/OPERATOR_DECISIONS.md"), 6000, extractActiveSections
    );
    if (activeDecisions) {
      parts.push(`\n--- OPERATOR_DECISIONS [ACTIVE] ---\n${activeDecisions}`);
    }

    // 4. BACKLOG.md
    const backlog = readTrimmed(
      path.join(root, "knowledge/memory/BACKLOG.md"), 2000
    );
    if (backlog) {
      parts.push(`\n--- BACKLOG (P0-P1 focus) ---\n${backlog}`);
    }

    // 5. MCP servers status (check from mcp.json config)
    const mcpConfigPath = path.join(root, ".cursor", "mcp.json");
    if (fs.existsSync(mcpConfigPath)) {
      try {
        const mcpConfig = JSON.parse(fs.readFileSync(mcpConfigPath, "utf8"));
        const servers = mcpConfig.mcpServers ? Object.keys(mcpConfig.mcpServers) : [];
        if (servers.length > 0) {
          parts.push(`\n--- MCP SERVERS CONFIGURED (${servers.length}) ---\n  ${servers.join(", ")}`);
        }
      } catch { }
    }

    // 5. DRIFT.md (recent drift — now auto-generated by arch-refresh hook)
    const driftLog = readTrimmed(
      path.join(root, "top-code-memory/DRIFT.md"), 1500,
      (text) => {
        const lines = text.split(/\r?\n/);
        const result = [];
        let inFirst = false;
        for (const line of lines) {
          if (/^##\s+\d{4}-\d{2}-\d{2}/.test(line)) {
            if (inFirst) break;
            inFirst = true;
          }
          if (inFirst) result.push(line);
        }
        return result.join("\n").trim() || null;
      }
    );
    if (driftLog) {
      parts.push(`\n--- DRIFT (since last session) ---\n${driftLog}`);
    }

    // 6. Pending work from last session closeout (sessionEnd hooks)
    const pendingReflection = readTrimmed(path.join(root, "top-code-memory/PENDING_REFLECTION.md"), 1500);
    if (pendingReflection) {
      parts.push(`\n--- PENDING REFLECTION (from session end) ---\n${pendingReflection}`);
    }
    const pendingAutoReview = readTrimmed(path.join(root, "top-code-memory/AUTO_REVIEW_PENDING.md"), 1200);
    if (pendingAutoReview) {
      parts.push(`\n--- AUTO-REVIEW PENDING (from session end) ---\n${pendingAutoReview}`);
    }
    const transcriptParse = readTrimmed(path.join(root, "top-code-memory/TRANSCRIPT_PARSE.md"), 1200);
    if (transcriptParse) {
      parts.push(`\n--- LAST TRANSCRIPT PARSE ---\n${transcriptParse}`);
    }

    // 7. LAST_SESSION — knowledge/memory is canonical (may be newer than Reflection)
    const lastSessionKnowledge = readTrimmed(
      path.join(root, "knowledge/memory/LAST_SESSION.md"), 2000
    );
    if (lastSessionKnowledge) {
      parts.push(`\n--- LAST SESSION (knowledge/memory) ---\n${lastSessionKnowledge}`);
    } else {
      const lastSessionMemory = readTrimmed(
        path.join(root, "top-code-memory/LAST_SESSION.md"), 2500
      );
      if (lastSessionMemory) {
        parts.push(`\n--- LAST SESSION (top-code-memory) ---\n${lastSessionMemory}`);
      }
    }

    parts.push(
      "\nMemory: top-code-memory/reflections/ · Decisions: knowledge/memory/OPERATOR_DECISIONS.md · " +
      "Backlog: knowledge/memory/BACKLOG.md · Local Docker only unless operator overrides."
    );

    process.stdout.write(JSON.stringify({ followup_message: parts.join("\n") }) + "\n");
    if (!manual) {
      try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }
    }
  } catch {
    process.stdout.write("{}\n");
  }
});
