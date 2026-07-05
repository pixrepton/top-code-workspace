/**
 * Session-stop transcript parser hook.
 *
 * Auto-detects the latest JSONL transcript and extracts key events:
 * decisions, files touched, proof gates, user turns.
 * Outputs a condensed structured summary for agent context.
 *
 * Called by .cursor/hooks.json "stop" hook.
 * Receives stdin JSON: { status: "completed", loop_count: 0 }
 */
const fs = require("fs");
const path = require("path");
const os = require("os");

const TRANSCRIPTS_DIR = path.join(os.tmpdir(), "cursor", "agent-transcripts");

const DECISION_PATTERNS = [
  /decyzja|decision/i, /rezygnujemy/i, /przenosimy/i, /zmieniamy/i,
  /refaktoryzacj/i, /migracj/i, /wdrażamy/i, /usuwamy/i,
  /dodajemy/i, /wprowadzamy/i, /zastępujemy/i,
  /konflikt/i, /rule \.mdc/i, /regul[ay]/i,
  /osobowość/i, /narzędzie/i, /tool/i,
  /SLA/i, /puls biznesu/i
];

const DECISION_PATTERNS = [
  /decyzja|decision/i, /rezygnujemy/i, /przenosimy/i, /zmieniamy/i,
  /refaktoryzacj/i, /migracj/i, /wdrażamy/i, /usuwamy/i,
  /dodajemy/i, /wprowadzamy/i, /zastępujemy/i,
  /konflikt/i, /rule \.mdc/i, /regul[ay]/i,
  /osobowość/i, /narzędzie/i, /tool/i,
  /SLA/i, /puls biznesu/i
];

const FILE_PATTERNS = [
  /"path":\s*"([^"]+\.(?:py|js|php|mdc|md|yml|yaml|json|ps1))"/gi,
];

const PROOF_GATE_PATTERNS = [
  /pytest|--check|test_.*\.py/i,
  /preflight|Gate A|Gate B/i,
  /proven_local|confirmed by local tests/i
];

function parseTranscript(filepath) {
  const content = fs.readFileSync(filepath, "utf8");
  const lines = content.split(/\r?\n/).filter(Boolean);

  const decisions = [];
  const files = [];
  const proofGates = [];
  let userTurns = 0;

  for (const line of lines) {
    try {
      const obj = JSON.parse(line);
      if (obj.role === "user") {
        userTurns++;
        const text = typeof obj.content === "string" ? obj.content : JSON.stringify(obj);
        for (const pat of DECISION_PATTERNS) {
          if (pat.test(text)) {
            decisions.push(text.slice(0, 120));
            break;
          }
        }
        for (const pat of PROOF_GATE_PATTERNS) {
          if (pat.test(text) && !proofGates.includes(text.slice(0, 80))) {
            proofGates.push(text.slice(0, 80));
          }
        }
      }
    } catch { }
  }

  // Extract file paths from tool calls
  for (const line of lines) {
    for (const pat of FILE_PATTERNS) {
      let match;
      while ((match = pat.exec(line)) !== null) {
        if (!files.includes(match[1])) files.push(match[1]);
      }
    }
  }

  return {
    userTurns,
    decisions: [...new Set(decisions)].slice(0, 10),
    files: [...new Set(files)].slice(0, 15),
    proofGates: [...new Set(proofGates)].slice(0, 5),
  };
}

function findLatestTranscript() {
  if (!fs.existsSync(TRANSCRIPTS_DIR)) return null;
  const files = fs.readdirSync(TRANSCRIPTS_DIR)
    .filter(f => f.endsWith(".jsonl"))
    .map(f => ({
      name: f,
      path: path.join(TRANSCRIPTS_DIR, f),
      mtime: fs.statSync(path.join(TRANSCRIPTS_DIR, f)).mtimeMs,
    }))
    .sort((a, b) => b.mtime - a.mtime);
  return files.length > 0 ? files[0].path : null;
}

const chunks = [];
process.stdin.on("data", (c) => chunks.push(c));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse((Buffer.concat(chunks).toString("utf8") || "{}").trim());
    const loopCount = Number(payload.loop_count || 0);

    if (loopCount > 0) {
      process.stdout.write("{}\n");
      return;
    }

    const transcriptPath = findLatestTranscript();
    if (!transcriptPath) {
      process.stdout.write(JSON.stringify({ followup_message: "[TRANSCRIPT PARSE] No transcript found." }) + "\n");
      return;
    }

    const result = parseTranscript(transcriptPath);
    if (result.userTurns === 0) {
      process.stdout.write(JSON.stringify({ followup_message: "[TRANSCRIPT PARSE] Transcript is empty or unparseable." }) + "\n");
      return;
    }

    const parts = [
      "--- SESSION TRANSCRIPT (parsed) ---",
      `User turns: ${result.userTurns}`,
    ];
    if (result.decisions.length > 0) {
      parts.push(`Decisions found: ${result.decisions.length}`);
      for (const d of result.decisions.slice(0, 5)) {
        parts.push(`  • ${d.slice(0, 100)}`);
      }
    }
    if (result.files.length > 0) {
      parts.push(`Files touched: ${result.files.length}`);
      for (const f of result.files.slice(0, 8)) {
        parts.push(`  • ${f}`);
      }
    }
    if (result.proofGates.length > 0) {
      parts.push(`Proof gates: ${result.proofGates.length}`);
      for (const g of result.proofGates) {
        parts.push(`  • ${g.slice(0, 80)}`);
      }
    }

    process.stdout.write(JSON.stringify({ followup_message: parts.join("\n") }) + "\n");
  } catch {
    process.stdout.write(JSON.stringify({ followup_message: "[TRANSCRIPT PARSE] Error parsing transcript." }) + "\n");
  }
});
