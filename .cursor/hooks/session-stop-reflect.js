/**
 * Session-stop reflection hook.
 *
 * WHAT THIS DOES:
 *   When the agent loop ends, this hook:
 *   1. Reads the transcript_path from stdin
 *   2. Evaluates whether the session warrants architectural reflection
 *   3. If yes: returns followup_message asking for a reflection subagent
 *   4. If no: returns {} (no follow-up needed)
 *
 * HEURISTICS for reflection:
 *   - Session has >10 turns (long discussion)
 *   - Session contains architectural decisions (keywords: architektura, decyzja, rezygnujemy, przenosimy...)
 *   - Session modified .mdc rules or AGENTS.md files
 *
 * ACTIVATION:
 *   Called by Cursor IDE via .cursor/hooks.json "stop" hook.
 *   Receives stdin JSON: { status, transcript_path, loop_count, conversation_id, ... }
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-session-reflect.lock");
const ROOT = path.join(__dirname, "..", "..");
const REFLECTIONS_DIR = path.join(ROOT, "top-code-memory", "reflections");

// Architectural decision keywords (case-insensitive)
const ARCH_KEYWORDS = [
  "architektura", "architektoniczn", "decyzja", "rezygnujemy", "przenosimy",
  "zmieniamy", "refaktoryzacja", "migracja", "wdrazamy", "usuwamy",
  "dodajemy nowy", "wprowadzamy", "zastepujemy", "konflikt",
  "rule .mdc", "regula", ".mdc", "AGENTS.md", "CLAUDE.md",
  "hook", "MCP", "permissions", "alwaysApply",
  // Expanded P1-B: agent personality, tools, business pulse
  "osobowosc", "narzedzie", "tool", "personality",
  "SLA", "puls biznesu", "business pulse", "operator memory",
  "constitution", "outbox", "token budget", "circuit breaker"
];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function countTurns(transcriptPath) {
  try {
    const content = fs.readFileSync(transcriptPath, "utf8");
    const lines = content.split(/\r?\n/).filter(Boolean);
    let userTurns = 0;
    for (const line of lines) {
      try {
        const obj = JSON.parse(line);
        if (obj.role === "user") userTurns++;
      } catch { /* skip malformed lines */ }
    }
    return userTurns;
  } catch {
    return 0;
  }
}

function scanForArchKeywords(transcriptPath) {
  try {
    const content = fs.readFileSync(transcriptPath, "utf8");
    const lower = content.toLowerCase();
    let matches = [];
    for (const kw of ARCH_KEYWORDS) {
      if (lower.includes(kw.toLowerCase())) {
        matches.push(kw);
      }
    }
    return matches;
  } catch {
    return [];
  }
}

function findChangedFiles(transcriptPath) {
  try {
    const content = fs.readFileSync(transcriptPath, "utf8");
    const changed = new Set();
    // Look for Write/StrReplace/Delete tool uses that touch .mdc or AGENTS.md
    const re = /"path":\s*"([^"]*(?:\.mdc|AGENTS\.md|CLAUDE\.md|\.cursorrules)[^"]*)"/gi;
    let match;
    while ((match = re.exec(content)) !== null) {
      changed.add(match[1]);
    }
    // Also detect constitution_*.py, business_pulse.py, operator_memory.py, handlers.py
    const re2 = /"path":\s*"([^"]*(?:constitution_|business_pulse|operator_memory|tools\/handlers)[^"]*)"/gi;
    while ((match = re2.exec(content)) !== null) {
      changed.add(match[1] + " [key file]");
    }
    return [...changed];
  } catch {
    return [];
  }
}

function shouldReflect(userTurns, archKeywords, changedFiles) {
  // Heuristic 1: >10 user turns = long session
  if (userTurns > 10) return true;

  // Heuristic 2: >1 architectural keyword found
  if (archKeywords.length > 1) return true;

  // Heuristic 3: .mdc or AGENTS.md files were modified
  if (changedFiles.length > 0) return true;

  return false;
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    let raw = Buffer.concat(chunks).toString("utf8").trim();
    if (!raw) raw = "{}";
    const payload = JSON.parse(raw);
    const status = payload.status;
    const transcriptPath = payload.transcript_path;
    const loopCount = Number(payload.loop_count || 0);
    const convoId = payload.conversation_id || "unknown";

    // Sentinel lock: only fire once per Cursor process
    if (fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    // Only reflect on completed sessions with an available transcript
    if (status !== "completed" || !transcriptPath || !fs.existsSync(transcriptPath)) {
      process.stdout.write("{}\n");
      try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }
      return;
    }

    // Prevent re-trigger loops
    if (loopCount > 0) {
      process.stdout.write("{}\n");
      return;
    }

    const userTurns = countTurns(transcriptPath);
    const archKeywords = scanForArchKeywords(transcriptPath);
    const changedFiles = findChangedFiles(transcriptPath);

    if (!shouldReflect(userTurns, archKeywords, changedFiles)) {
      process.stdout.write("{}\n");
      try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }
      return;
    }

    // Build the reflection instruction for the followup agent
    const date = new Date().toISOString().split("T")[0];
    const slug = date + "-reflection";

    const msg = [
      "[REFLECTION HOOK] Sesja " + convoId.slice(0, 8) + " zawiera decyzje architektoniczne.",
      "Wykryto: " + userTurns + " tur, " + archKeywords.length + " slow kluczowych, " + changedFiles.length + " zmienionych plikow konfiguracyjnych.",
      "",
      "Uruchom subagenta (Task tool) do refleksji nad ta sesja. Instrukcje:",
      "",
      "1. Przeczytaj pelna transkrypcje z: " + transcriptPath,
      "2. Wyekstrahuj wszystkie decyzje architektoniczne wraz z uzasadnieniami",
      "3. Dla kazdej decyzji podaj: kontekst, argumenty za/przeciw, cytat z transkryptu",
      "4. Zapisz Reflection do: top-code-memory/reflections/" + slug + ".md",
      "5. Uzyj formatu: ## Decyzje architektoniczne, ## Stan koncowy, ## Wzorce, ## Co dalej",
      "6. Kazda decyzja musi miec sekcje Uzasadnienie z cytatami z transkryptu",
      "7. Zapisz kopie transkryptu do: top-code-memory/sessions/" + slug + ".jsonl",
    ].join("\n");

    // Write sentinel lock
    try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }

    process.stdout.write(JSON.stringify({ followup_message: msg }) + "\n");
  } catch (err) {
    process.stdout.write(JSON.stringify({ followup_message: "[reflect error] " + err.message }) + "\n");
  }
});
