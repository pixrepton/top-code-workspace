/**
 * Session-end engram writer.
 *
 * Archives LAST_SESSION.md into top-code-memory/sessions/.
 * Does NOT inject followup_message into chat.
 *
 * ACTIVATION:
 *   .cursor/hooks.json "sessionEnd" or scripts/run-session-stop-hooks.ps1
 */

const fs = require("fs");
const path = require("path");

const {
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const ROOT = path.join(__dirname, "..", "..");
const MEMORY_DIR = path.join(ROOT, "top-code-memory");
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

function updateIndex(slug, title, summary) {
  ensureFile(INDEX_PATH, "# TOP-CODE Memory Index\n\nNo sessions yet.\n");
  let index = fs.readFileSync(INDEX_PATH, "utf8");
  const tableMarker = "## Sessions";
  if (!index.includes(tableMarker)) {
    index += `\n${tableMarker}\n\n| Date | Tag | Summary | File |\n|------|-----|---------|------|\n`;
  }
  const slugMarker = `sessions/${slug}.md`;
  if (!index.includes(slugMarker)) {
    const tableSection = index.indexOf("| Date | Tag |");
    if (tableSection >= 0) {
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

readStdinPayload().then((payload) => {
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId || "unknown";
    const status = payload.status;

    if (!acquireSessionEndLock(`engram-${convoId}`, manual)) {
      process.stdout.write("{}\n");
      return;
    }

    let sessionFile = LAST_SESSION_SRC;
    if (!fs.existsSync(sessionFile)) sessionFile = LAST_SESSION_KNOWLEDGE;

    if (!fs.existsSync(sessionFile)) {
      writeCloseoutLog(ROOT, [
        "[engram] No LAST_SESSION.md — nothing to archive.",
      ]);
      process.stdout.write("{}\n");
      return;
    }

    const content = fs.readFileSync(sessionFile, "utf8");
    if (!content || content.trim().length < 50) {
      writeCloseoutLog(ROOT, [
        "[engram] LAST_SESSION.md too short — skipped.",
      ]);
      process.stdout.write("{}\n");
      return;
    }

    const title = extractTitle(content);
    const dateMatch = content.match(/(?:Duration|Date).*?(\d{4}-\d{2}-\d{2})/);
    const sessionDate = dateMatch ? dateMatch[1] : new Date().toISOString().split("T")[0];
    let cleanTitle = title.replace(/^\d{4}[-\/]\d{2}[-\/]\d{2}(?:\/\d{2})?\s*/, "").trim();
    cleanTitle = cleanTitle.replace(/^[([{]+/, "").replace(/[)\]}]$/, "").trim();
    const slugPart = cleanTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    const slug = sessionDate + "-" + (slugPart || "session");
    const summary = title.length < 80 ? title : title.slice(0, 80) + "...";

    ensureDir(SESSIONS_DIR);
    const archivePath = path.join(SESSIONS_DIR, `${slug}.md`);
    const archived = !fs.existsSync(archivePath);
    if (archived) {
      fs.writeFileSync(archivePath, content, "utf8");
      updateIndex(slug, title, summary);
    }

    const log = [
      `[engram] ${archived ? "SAVED" : "already archived"}`,
      `  file: top-code-memory/sessions/${slug}.md`,
      `  title: ${title.slice(0, 60)}`,
    ];
    if (status && status !== "completed") {
      log.push("  note: session status was not completed");
    }
    writeCloseoutLog(ROOT, log);
    process.stdout.write("{}\n");
  } catch (err) {
    writeCloseoutLog(ROOT, [`[engram] ERROR: ${err.message}`]);
    process.stdout.write("{}\n");
  }
});
