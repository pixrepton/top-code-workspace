/**
 * Session-end reflection hook.
 *
 * Evaluates whether the session warrants architectural reflection.
 * If yes: writes top-code-memory/PENDING_REFLECTION.md (picked up on next sessionStart).
 * Does NOT inject followup_message — sessionEnd has no live agent loop.
 *
 * ACTIVATION:
 *   .cursor/hooks.json "sessionEnd" or scripts/run-session-stop-hooks.ps1
 */

const fs = require("fs");
const path = require("path");

const {
  countRealUserTurns,
  iterateUserQueries,
  findLatestTranscript,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const ROOT = path.join(__dirname, "..", "..");
const REFLECTIONS_DIR = path.join(ROOT, "top-code-memory", "reflections");
const PENDING_PATH = path.join(ROOT, "top-code-memory", "PENDING_REFLECTION.md");

const ARCH_KEYWORDS = [
  "architektura", "architektoniczn", "decyzja", "rezygnujemy", "przenosimy",
  "zmieniamy", "refaktoryzacja", "migracja", "wdrazamy", "usuwamy",
  "dodajemy nowy", "wprowadzamy", "zastepujemy", "konflikt",
  "rule .mdc", "regula", ".mdc", "AGENTS.md", "CLAUDE.md",
  "hook", "MCP", "permissions", "alwaysApply",
  "osobowosc", "narzedzie", "personality",
  "SLA", "puls biznesu", "business pulse", "operator memory",
  "constitution", "outbox", "token budget", "circuit breaker",
];

function scanForArchKeywords(transcriptPath) {
  const matches = new Set();
  iterateUserQueries(transcriptPath, (query) => {
    const lower = query.toLowerCase();
    for (const kw of ARCH_KEYWORDS) {
      if (lower.includes(kw.toLowerCase())) matches.add(kw);
    }
  });
  return [...matches];
}

function findChangedFiles(transcriptPath) {
  try {
    const content = fs.readFileSync(transcriptPath, "utf8");
    const changed = new Set();
    const re = /"path":\s*"([^"]*(?:\.mdc|AGENTS\.md|CLAUDE\.md|\.cursorrules)[^"]*)"/gi;
    let match;
    while ((match = re.exec(content)) !== null) changed.add(match[1]);
    const re2 = /"path":\s*"([^"]*(?:constitution_|business_pulse|operator_memory|tools\/handlers)[^"]*)"/gi;
    while ((match = re2.exec(content)) !== null) changed.add(match[1]);
    return [...changed];
  } catch {
    return [];
  }
}

function shouldReflect(userTurns, archKeywords, changedFiles) {
  if (userTurns > 10) return true;
  if (archKeywords.length > 1) return true;
  if (changedFiles.length > 0) return true;
  return false;
}

readStdinPayload().then((payload) => {
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId || "unknown";
    const transcriptPath = payload.transcript_path || findLatestTranscript();

    if (!acquireSessionEndLock(`reflect-${convoId}`, manual)) {
      process.stdout.write("{}\n");
      return;
    }

    if (!transcriptPath || !fs.existsSync(transcriptPath)) {
      writeCloseoutLog(ROOT, ["[reflect] No transcript — skipped."]);
      process.stdout.write("{}\n");
      return;
    }

    const userTurns = countRealUserTurns(transcriptPath);
    const archKeywords = scanForArchKeywords(transcriptPath);
    const changedFiles = findChangedFiles(transcriptPath);

    if (!shouldReflect(userTurns, archKeywords, changedFiles)) {
      writeCloseoutLog(ROOT, ["[reflect] No reflection needed."]);
      process.stdout.write("{}\n");
      return;
    }

    const date = new Date().toISOString().split("T")[0];
    const slug = `${date}-reflection`;
    const pending = [
      "# Pending reflection (session end)",
      "",
      `Created: ${new Date().toISOString()}`,
      `Session: ${convoId.slice(0, 12)}`,
      `Transcript: ${transcriptPath}`,
      `User turns: ${userTurns} | Keywords: ${archKeywords.length} | Config files: ${changedFiles.length}`,
      "",
      "## Agent instructions (next session or manual run)",
      "",
      "1. Read full transcript from path above",
      "2. Extract architectural decisions with justifications and transcript quotes",
      "3. Write Reflection to: top-code-memory/reflections/" + slug + ".md",
      "4. Format: ## Decyzje architektoniczne, ## Stan koncowy, ## Wzorce, ## Co dalej",
      "5. Archive transcript copy to: top-code-memory/sessions/" + slug + ".jsonl",
      "6. Delete this file after reflection is saved",
      "",
    ].join("\n");

    const dir = path.dirname(PENDING_PATH);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(PENDING_PATH, pending, "utf8");

    writeCloseoutLog(ROOT, [
      "[reflect] Reflection pending",
      `  file: top-code-memory/PENDING_REFLECTION.md`,
      `  turns: ${userTurns}, keywords: ${archKeywords.join(", ").slice(0, 80)}`,
    ]);
    process.stdout.write("{}\n");
  } catch (err) {
    writeCloseoutLog(ROOT, [`[reflect] ERROR: ${err.message}`]);
    process.stdout.write("{}\n");
  }
});
