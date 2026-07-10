/**
 * Session-end transcript parser.
 *
 * Parses JSONL transcript, writes summary to top-code-memory/TRANSCRIPT_PARSE.md.
 * Does NOT inject followup_message into chat (sessionEnd = fire-and-forget).
 *
 * Called by .cursor/hooks.json "sessionEnd" or scripts/run-session-stop-hooks.ps1
 */
const fs = require("fs");
const path = require("path");

const {
  iterateUserQueries,
  countRealUserTurns,
  findLatestTranscript,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const WORKSPACE_ROOT = path.join(__dirname, "..", "..");
const OUTPUT_PATH = path.join(WORKSPACE_ROOT, "top-code-memory", "TRANSCRIPT_PARSE.md");

const DECISION_PATTERNS = [
  /decyzja|decision/i, /rezygnujemy/i, /przenosimy/i, /zmieniamy/i,
  /refaktoryzacj/i, /migracj/i, /wdrażamy/i, /usuwamy/i,
  /dodajemy/i, /wprowadzamy/i, /zastępujemy/i,
  /konflikt/i, /rule \.mdc/i, /regul[ay]/i,
  /osobowość/i, /SLA/i, /puls biznesu/i,
];

const FILE_PATTERNS = [
  /"path":\s*"([^"]+\.(?:py|js|php|mdc|md|yml|yaml|json|ps1))"/gi,
];

const PROOF_GATE_PATTERNS = [
  /pytest|--check|test_.*\.py/i,
  /preflight|Gate A|Gate B/i,
  /proven_local|confirmed by local tests/i,
];

function parseTranscript(filepath) {
  const decisions = [];
  const proofGates = [];
  const files = [];

  iterateUserQueries(filepath, (query) => {
    for (const pat of DECISION_PATTERNS) {
      if (pat.test(query)) {
        decisions.push(query.slice(0, 200));
        break;
      }
    }
    for (const pat of PROOF_GATE_PATTERNS) {
      const snippet = query.slice(0, 120);
      if (pat.test(query) && !proofGates.includes(snippet)) {
        proofGates.push(snippet);
      }
    }
  });

  const lines = fs.readFileSync(filepath, "utf8").split(/\r?\n/).filter(Boolean);
  for (const line of lines) {
    for (const pat of FILE_PATTERNS) {
      let match;
      while ((match = pat.exec(line)) !== null) {
        if (!files.includes(match[1])) files.push(match[1]);
      }
    }
  }

  return {
    userTurns: countRealUserTurns(filepath),
    decisions: [...new Set(decisions)].slice(0, 10),
    files: [...new Set(files)].slice(0, 20),
    proofGates: [...new Set(proofGates)].slice(0, 5),
  };
}

function formatSummary(result, transcriptPath) {
  const parts = [
    "# Session transcript parse",
    "",
    `Parsed: ${new Date().toISOString()}`,
    `Source: ${transcriptPath}`,
    "",
    `User turns (real): ${result.userTurns}`,
    "",
  ];
  if (result.decisions.length > 0) {
    parts.push(`## Decisions (${result.decisions.length})`, "");
    for (const d of result.decisions.slice(0, 8)) {
      parts.push(`- ${d.replace(/\s+/g, " ").slice(0, 160)}`);
    }
    parts.push("");
  }
  if (result.files.length > 0) {
    parts.push(`## Files touched (${result.files.length})`, "");
    for (const f of result.files.slice(0, 15)) {
      parts.push(`- \`${f}\``);
    }
    parts.push("");
  }
  if (result.proofGates.length > 0) {
    parts.push(`## Proof gates (${result.proofGates.length})`, "");
    for (const g of result.proofGates) {
      parts.push(`- ${g.replace(/\s+/g, " ").slice(0, 120)}`);
    }
    parts.push("");
  }
  return parts.join("\n");
}

readStdinPayload().then((payload) => {
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId;

    if (!acquireSessionEndLock(convoId, manual)) {
      process.stdout.write("{}\n");
      return;
    }

    const transcriptPath = payload.transcript_path || findLatestTranscript();
    if (!transcriptPath || !fs.existsSync(transcriptPath)) {
      writeCloseoutLog(WORKSPACE_ROOT, ["[parse-transcript] No transcript found."]);
      process.stdout.write("{}\n");
      return;
    }

    const result = parseTranscript(transcriptPath);
    if (result.userTurns === 0) {
      writeCloseoutLog(WORKSPACE_ROOT, ["[parse-transcript] No real user turns in transcript."]);
      process.stdout.write("{}\n");
      return;
    }

    const summary = formatSummary(result, transcriptPath);
    const outDir = path.dirname(OUTPUT_PATH);
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(OUTPUT_PATH, summary, "utf8");

    writeCloseoutLog(WORKSPACE_ROOT, [
      "[parse-transcript] OK",
      `  turns: ${result.userTurns}`,
      `  decisions: ${result.decisions.length}`,
      `  files: ${result.files.length}`,
      `  output: top-code-memory/TRANSCRIPT_PARSE.md`,
    ]);
    process.stdout.write("{}\n");
  } catch (err) {
    writeCloseoutLog(WORKSPACE_ROOT, [`[parse-transcript] ERROR: ${err.message}`]);
    process.stdout.write("{}\n");
  }
});
