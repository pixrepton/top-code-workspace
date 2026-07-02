/**
 * Pass 1: Transcript parser for reflection (no LLM).
 * Extracts key events from JSONL transcript: decisions, files, proof gates.
 * Output: condensed structured summary (<200 words).
 */
const fs = require("fs");

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

// CLI
const filepath = process.argv[2];
if (!filepath) {
  process.stderr.write("Usage: node session-stop-parse-transcript.js <transcript.jsonl>\n");
  process.exit(1);
}

const result = parseTranscript(filepath);
process.stdout.write(JSON.stringify(result, null, 2) + "\n");
