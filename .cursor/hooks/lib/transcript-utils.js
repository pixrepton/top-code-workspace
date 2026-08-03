/**
 * Shared transcript parsing for session-end hooks.
 * Supports current Cursor JSONL format: { role, message: { content: [{type,text}] } }
 */
const fs = require("fs");
const path = require("path");
const os = require("os");

const TRANSCRIPTS_DIR = path.join(os.tmpdir(), "cursor", "agent-transcripts");
const SESSION_SCRATCH_ROOT =
  process.env.TOP_CODE_SESSION_SCRATCH ||
  path.join(process.env.SystemDrive || "C:", "top-code-session-scratch");

const HOOK_NOISE_PATTERNS = [
  /--- SESSION TRANSCRIPT \(parsed\) ---/,
  /TOP-INSTAL session context \(auto-injected\)/,
  /\[ARCH CHECK\]/,
  /🏗️\s+ARCHITECTURE REFRESH/,
  /SESSION ENGRAM/,
  /\[REFLECTION HOOK\]/,
  /--- AUTO-REVIEW/,
  /\[TRANSCRIPT PARSE\]/,
];

function extractUserText(obj) {
  if (!obj || obj.role !== "user") return null;
  if (typeof obj.content === "string") return obj.content;
  const msg = obj.message;
  if (msg && Array.isArray(msg.content)) {
    return msg.content
      .filter((p) => p && p.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("\n");
  }
  if (Array.isArray(obj.content)) {
    return obj.content
      .filter((p) => p && p.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("\n");
  }
  return null;
}

function extractUserQuery(text) {
  if (!text) return "";
  const m = text.match(/<user_query>\s*([\s\S]*?)\s*<\/user_query>/i);
  return (m ? m[1] : text).trim();
}

function isHookNoise(text) {
  if (!text) return true;
  return HOOK_NOISE_PATTERNS.some((p) => p.test(text));
}

function isRealUserTurn(obj) {
  const raw = extractUserText(obj);
  if (!raw) return false;
  const query = extractUserQuery(raw);
  if (!query || isHookNoise(query)) return false;
  return true;
}

function readTranscriptLines(filepath) {
  try {
    const content = fs.readFileSync(filepath, "utf8");
    return content.split(/\r?\n/).filter(Boolean);
  } catch {
    return [];
  }
}

function iterateUserQueries(filepath, fn) {
  const lines = readTranscriptLines(filepath);
  for (const line of lines) {
    try {
      const obj = JSON.parse(line);
      if (!isRealUserTurn(obj)) continue;
      const query = extractUserQuery(extractUserText(obj));
      fn(query, obj);
    } catch {
      /* skip malformed */
    }
  }
}

function countRealUserTurns(filepath) {
  let n = 0;
  iterateUserQueries(filepath, () => {
    n++;
  });
  return n;
}

function findLatestTranscript() {
  const candidates = [
    TRANSCRIPTS_DIR,
    path.join(os.homedir(), ".cursor", "projects"),
  ];

  const files = [];
  for (const base of candidates) {
    if (!fs.existsSync(base)) continue;
    if (base.endsWith("projects")) {
      // Scan project agent-transcripts: .../agent-transcripts/<id>/<id>.jsonl
      try {
        for (const projectDir of fs.readdirSync(base)) {
          const transcriptsRoot = path.join(base, projectDir, "agent-transcripts");
          if (!fs.existsSync(transcriptsRoot)) continue;
          collectJsonlFiles(transcriptsRoot, files, 3);
        }
      } catch { /* best-effort */ }
      continue;
    }
    collectJsonlFiles(base, files, 2);
  }

  if (files.length === 0) return null;
  files.sort((a, b) => b.mtime - a.mtime);
  return files[0].path;
}

function collectJsonlFiles(dir, out, depth) {
  if (depth <= 0) return;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isFile() && ent.name.endsWith(".jsonl") && !full.includes(`${path.sep}subagents${path.sep}`)) {
      try {
        out.push({ path: full, mtime: fs.statSync(full).mtimeMs });
      } catch { /* skip */ }
    } else if (ent.isDirectory()) {
      collectJsonlFiles(full, out, depth - 1);
    }
  }
}

const CLOSEOUT_MAX_ENTRIES = 150;
const SESSION_END_LOCK_MAX_AGE_MS = 6 * 60 * 60 * 1000;

function isStaleLock(lockPath) {
  try {
    const raw = fs.readFileSync(lockPath, "utf8").trim();
    const ts = Date.parse(raw);
    if (!Number.isFinite(ts)) return true;
    return Date.now() - ts > SESSION_END_LOCK_MAX_AGE_MS;
  } catch {
    return true;
  }
}

function sessionEndLockPath(conversationId) {
  const safe = (conversationId || "unknown").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64);
  return path.join(os.tmpdir(), `cursor-session-end-${safe}.lock`);
}

function acquireSessionEndLock(conversationId, manual) {
  if (manual) return true;
  const lock = sessionEndLockPath(conversationId);
  if (fs.existsSync(lock)) {
    if (!isStaleLock(lock)) return false;
    try {
      fs.unlinkSync(lock);
    } catch {
      return false;
    }
  }
  try {
    fs.writeFileSync(lock, new Date().toISOString(), "utf8");
  } catch {
    return false;
  }
  return true;
}

function readStdinPayload() {
  return new Promise((resolve) => {
    const chunks = [];
    process.stdin.on("data", (c) => chunks.push(c));
    process.stdin.on("end", () => {
      try {
        const raw = (Buffer.concat(chunks).toString("utf8") || "{}").trim();
        resolve(JSON.parse(raw || "{}"));
      } catch {
        resolve({});
      }
    });
  });
}

function rotateCloseoutLog(logPath) {
  if (!fs.existsSync(logPath)) return;
  const content = fs.readFileSync(logPath, "utf8");
  const parts = content.split(/\n(?=## \d{4}-\d{2}-\d{2}T)/).filter(Boolean);
  if (parts.length <= CLOSEOUT_MAX_ENTRIES) return;
  const kept = parts.slice(-CLOSEOUT_MAX_ENTRIES).join("\n").trimStart();
  fs.writeFileSync(logPath, kept.endsWith("\n") ? kept : `${kept}\n`, "utf8");
}

function writeCloseoutLog(workspaceRoot, lines) {
  const logPath = path.join(SESSION_SCRATCH_ROOT, "SESSION_CLOSEOUT.log");
  const dir = path.dirname(logPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const entry = [
    `\n## ${new Date().toISOString()}`,
    ...lines,
    "",
  ].join("\n");
  fs.appendFileSync(logPath, entry, "utf8");
  rotateCloseoutLog(logPath);
}

module.exports = {
  TRANSCRIPTS_DIR,
  SESSION_SCRATCH_ROOT,
  HOOK_NOISE_PATTERNS,
  extractUserText,
  extractUserQuery,
  isHookNoise,
  isRealUserTurn,
  readTranscriptLines,
  iterateUserQueries,
  countRealUserTurns,
  findLatestTranscript,
  sessionEndLockPath,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
};
