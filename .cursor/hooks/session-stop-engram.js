/**
 * Session-stop engram writer.
 *
 * WHAT THIS DOES:
 *   When a session ends with status=completed, this hook:
 *   1. Archives the current LAST_SESSION.md into top-code-memory/sessions/ with a dated name
 *   2. Updates top-code-memory/INDEX.md with the new session entry
 *   3. Outputs a followup message summarizing what was saved
 *
 *   This makes every session persistent and searchable — no more lost work.
 *
 * ACTIVATION:
 *   Called by Cursor IDE via .cursor/hooks.json "stop" hook.
 *   Receives stdin JSON: { status: "completed", loop_count: 0 }
 *
 * FILE STRUCTURE:
 *   top-code-memory/
 *     INDEX.md           ← master session index (appended)
 *     LAST_SESSION.md    ← current session (overwritten by agent)
 *     sessions/
 *       YYYY-MM-DD-slug.md  ← archived engram (written here)
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-session-stop-archived.lock");
const MEMORY_DIR = path.join(__dirname, "..", "..", "top-code-memory");
const SESSIONS_DIR = path.join(MEMORY_DIR, "sessions");
const INDEX_PATH = path.join(MEMORY_DIR, "INDEX.md");
const LAST_SESSION_SRC = path.join(MEMORY_DIR, "LAST_SESSION.md");
const LAST_SESSION_KNOWLEDGE = path.join(__dirname, "..", "..", "knowledge", "memory", "LAST_SESSION.md");

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function ensureFile(fp, defaultContent) {
  if (!fs.existsSync(fp)) {
    ensureDir(path.dirname(fp));
    fs.writeFileSync(fp, defaultContent, "utf8");
  }
}

function now() {
  return new Date().toISOString();
}

function makeSlug(dateStr) {
  // dateStr like "2026-06-28/29" → "2026-06-28-29"
  return dateStr.replace(/[\/\s,:]+/g, "-").replace(/-+$/, "");
}

/**
 * Extract a title from the session markdown (first # line after "Last session —")
 */
function extractTitle(text) {
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    const m = line.match(/^#\s+.*?(?:[-–—]|\d{4}).*?\s+(.+)/);
    if (m) return m[1].trim();
    const m2 = line.match(/^#\s+(?:Last|Session|Engram).*?[-–—]\s+(.+)/);
    if (m2) return m2[1].trim();
  }
  return new Date().toISOString().split("T")[0] + "-session";
}

/**
 * Extract the "Next" section from a session
 */
function extractNext(text) {
  const lines = text.split(/\r?\n/);
  let inNext = false;
  const nextLines = [];
  for (const line of lines) {
    if (/^##\s+Next/i.test(line)) {
      inNext = true;
      continue;
    }
    if (inNext) {
      if (/^##\s/.test(line)) break;
      nextLines.push(line);
    }
  }
  return nextLines.filter(Boolean).slice(0, 6).join(" ").trim();
}

function updateIndex(slug, sessionDate, title, summary) {
  ensureFile(INDEX_PATH, "# TOP-CODE Memory Index\n\nNo sessions yet.\n");

  let index = fs.readFileSync(INDEX_PATH, "utf8");

  // Find the sessions table or create it
  const tableMarker = "## Sessions";
  if (!index.includes(tableMarker)) {
    index += `\n${tableMarker}\n\n| Date | Tag | Summary | File |\n|------|-----|---------|------|\n`;
  }

  // Check if this session file is already in the index
  const slugMarker = `sessions/${slug}.md`;
  if (!index.includes(slugMarker)) {
    // Find the table body and add an entry BEFORE the first session (newest first is implicit)
    const tableSection = index.indexOf("| Date | Tag |");
    if (tableSection >= 0) {
      // Find end of header row (next line after |------|-----|)
      const afterHeader = index.indexOf("|------|", tableSection);
      if (afterHeader >= 0) {
        const afterDivider = index.indexOf("\n", afterHeader);
        if (afterDivider >= 0) {
          const entry = `| ${slug} | ${slug} | ${summary} | sessions/${slug}.md |`;
          index = index.slice(0, afterDivider + 1) + entry + "\n" + index.slice(afterDivider + 1);
        }
      }
    }
  }

  fs.writeFileSync(INDEX_PATH, index, "utf8");
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    let raw = Buffer.concat(chunks).toString("utf8").trim();
    if (!raw) raw = "{}";
    const payload = JSON.parse(raw);
    const status = payload.status;
    const loopCount = Number(payload.loop_count || 0);

    // Prevent re-trigger loops: if this is a follow-up invocation, skip
    if (loopCount > 0) {
      process.stdout.write(JSON.stringify({ followup_message: "[engram] loop skipped (loop_count>0)" }) + "\n");
      return;
    }

    // Sentinel lock: archive only ONCE per Cursor process (per conversation lifetime)
    if (fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    // Always try to archive LAST_SESSION if it exists
    let sessionFile = LAST_SESSION_SRC;
    if (!fs.existsSync(sessionFile)) {
      sessionFile = LAST_SESSION_KNOWLEDGE;
    }

    if (!fs.existsSync(sessionFile)) {
      process.stdout.write(JSON.stringify({ followup_message: "No LAST_SESSION.md found — nothing to archive." }) + "\n");
      return;
    }

    const content = fs.readFileSync(sessionFile, "utf8");
    if (!content || content.trim().length < 50) {
      process.stdout.write(JSON.stringify({ followup_message: "LAST_SESSION.md is empty — nothing to archive." }) + "\n");
      return;
    }

    // Extract title and create slug
    const title = extractTitle(content);
    // Create slug from date: take first line matching "Date: YYYY-MM-DD" or use today
    const dateMatch = content.match(/(?:Duration|Date).*?(\d{4}-\d{2}-\d{2})/);
    const sessionDate = dateMatch ? dateMatch[1] : new Date().toISOString().split("T")[0];
    // Clean the title: remove leading date portion if present
    let cleanTitle = title.replace(/^\d{4}[-\/]\d{2}[-\/]\d{2}(?:\/\d{2})?\s*/, "").trim();
    cleanTitle = cleanTitle.replace(/^[([{]+/, "").replace(/[)\]}]$/, "").trim();
    const slugPart = cleanTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    const slug = sessionDate + "-" + (slugPart || "session");
    const summary = title.length < 80 ? title : title.slice(0, 80) + "...";
    const nextSteps = extractNext(content);

    // Save to sessions archive (only if not already archived)
    let archived = false;
    ensureDir(SESSIONS_DIR);
    const archivePath = path.join(SESSIONS_DIR, `${slug}.md`);
    if (!fs.existsSync(archivePath)) {
      fs.writeFileSync(archivePath, content, "utf8");
      archived = true;
    } else {
      archived = false;
    }

    // Update INDEX only if a NEW session file was written (archived=true)
    if (archived) {
      updateIndex(slug, sessionDate, title, summary);
    }

    // Build followup message
    const lines = [
      "SESSION ENGRAM " + (archived ? "SAVED" : "ALREADY ARCHIVED (skipped)"),
      "",
      `  File: top-code-memory/sessions/${slug}.md`,
      `  Title: ${title}`,
      `  INDEX: updated`,
      "",
    ];
    if (nextSteps) {
      lines.push("  Next steps from session:");
      for (const ns of nextSteps.split(". ").filter(Boolean).slice(0, 3)) {
        lines.push(`    • ${ns.trim()}${ns.trim().endsWith(".") ? "" : "."}`);
      }
      lines.push("");
    }
    lines.push("  To revisit: open top-code-memory/INDEX.md and find the session.");
    if (status !== "completed") {
      lines.push("");
      lines.push("⚠️  Session did not end with status=completed — partial save.");
    }

    process.stdout.write(JSON.stringify({ followup_message: lines.join("\n") }) + "\n");
    // Write sentinel lock
    try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }
  } catch (err) {
    process.stdout.write(JSON.stringify({ followup_message: `[engram error] ${err.message}` }) + "\n");
  }
});
