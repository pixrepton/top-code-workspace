/**
 * Session-end auto-review (divergence loop).
 *
 * Scans transcript for divergence candidates; writes top-code-memory/AUTO_REVIEW_PENDING.md
 * when found. Does NOT inject followup_message into chat.
 *
 * ACTIVATION:
 *   .cursor/hooks.json "sessionEnd" or scripts/run-session-stop-hooks.ps1
 */
const fs = require("fs");
const path = require("path");

const {
  iterateUserQueries,
  findLatestTranscript,
  acquireSessionEndLock,
  readStdinPayload,
  writeCloseoutLog,
} = require("./lib/transcript-utils");

const ROOT = path.join(__dirname, "..", "..");
const OUTPUT_PATH = path.join(ROOT, "top-code-memory", "AUTO_REVIEW_PENDING.md");

const PROPOSAL_PATTERNS = [
  /propozycj|proposal|sugest|suggest|zasuger/i,
  /agent\s*(propon|propos)/i,
  /maybe_create_learning_candidate/i,
  /learning_rule_candidate/i,
  /divergence/i,
  /operator\s*(edyt|edit|zmieni|change)/i,
  /EDITED_MATCH|DIVERGENT_ACTION/i,
];

const OPERATOR_EDIT_PATTERNS = [
  /operator\s*(edytował|edytowal|zmienił|zmienil|zaakceptował|zaakceptowal)/i,
  /hitl_edit|hitl_approve/i,
  /operator\s*response/i,
  /zatwierdz.*po edycji/i,
];

const RULE_DECISION_PATTERNS = [
  /uczymy.*się|uczymy.*sie|reguł|regul|rule.*candidate/i,
  /zatwierdz|odrzuc|approve|reject|rejected|approved/i,
  /playbook|pattern_key|candidate_id/i,
];

function scanTranscript(filepath) {
  const proposals = [];
  const operatorEdits = [];
  const ruleDecisions = [];

  iterateUserQueries(filepath, (query) => {
    for (const pat of PROPOSAL_PATTERNS) {
      if (pat.test(query)) {
        proposals.push(query.slice(0, 200));
        break;
      }
    }
    for (const pat of OPERATOR_EDIT_PATTERNS) {
      if (pat.test(query)) {
        operatorEdits.push(query.slice(0, 200));
        break;
      }
    }
    for (const pat of RULE_DECISION_PATTERNS) {
      if (pat.test(query)) {
        ruleDecisions.push(query.slice(0, 200));
        break;
      }
    }
  });

  const uniqueProposals = [...new Set(proposals)].slice(0, 10);
  const uniqueEdits = [...new Set(operatorEdits)].slice(0, 10);
  const uniqueRules = [...new Set(ruleDecisions)].slice(0, 10);

  return {
    proposals: uniqueProposals,
    operatorEdits: uniqueEdits,
    ruleDecisions: uniqueRules,
    hasDivergenceActivity: uniqueProposals.length > 0 && uniqueEdits.length > 0,
    totalCandidates: Math.min(uniqueProposals.length, uniqueEdits.length),
  };
}

function formatFile(result, convoId, transcriptPath) {
  const parts = [
    "# Auto-review: divergence candidates",
    "",
    `Created: ${new Date().toISOString()}`,
    `Session: ${convoId}`,
    `Transcript: ${transcriptPath}`,
    `Candidates: ~${result.totalCandidates}`,
    "",
  ];
  if (result.proposals.length > 0) {
    parts.push("## Proposals", "");
    for (const p of result.proposals.slice(0, 5)) {
      parts.push(`- ${p.replace(/\s+/g, " ").slice(0, 160)}`);
    }
    parts.push("");
  }
  if (result.operatorEdits.length > 0) {
    parts.push("## Operator edits", "");
    for (const e of result.operatorEdits.slice(0, 5)) {
      parts.push(`- ${e.replace(/\s+/g, " ").slice(0, 160)}`);
    }
    parts.push("");
  }
  if (result.ruleDecisions.length > 0) {
    parts.push("## Rule decisions", "");
    for (const d of result.ruleDecisions.slice(0, 3)) {
      parts.push(`- ${d.replace(/\s+/g, " ").slice(0, 160)}`);
    }
    parts.push("");
  }
  parts.push(
    "## Next steps",
    "",
    "Persist learning_rule_candidate records (source: auto_review) for operator review.",
    "Delete this file after processing.",
    "",
  );
  return parts.join("\n");
}

readStdinPayload().then((payload) => {
  try {
    const manual = Boolean(payload.manual);
    const convoId = payload.conversation_id || payload.conversationId || "unknown";
    const transcriptPath = payload.transcript_path || findLatestTranscript();

    if (!acquireSessionEndLock(`auto-review-${convoId}`, manual)) {
      process.stdout.write("{}\n");
      return;
    }

    if (!transcriptPath || !fs.existsSync(transcriptPath)) {
      writeCloseoutLog(ROOT, ["[auto-review] No transcript — skipped."]);
      process.stdout.write("{}\n");
      return;
    }

    const result = scanTranscript(transcriptPath);
    if (!result.hasDivergenceActivity) {
      writeCloseoutLog(ROOT, ["[auto-review] No divergence activity."]);
      process.stdout.write("{}\n");
      return;
    }

    const outDir = path.dirname(OUTPUT_PATH);
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(OUTPUT_PATH, formatFile(result, convoId.slice(0, 12), transcriptPath), "utf8");

    writeCloseoutLog(ROOT, [
      "[auto-review] Candidates found",
      `  count: ~${result.totalCandidates}`,
      `  file: top-code-memory/AUTO_REVIEW_PENDING.md`,
    ]);
    process.stdout.write("{}\n");
  } catch (err) {
    writeCloseoutLog(ROOT, [`[auto-review] ERROR: ${err.message}`]);
    process.stdout.write("{}\n");
  }
});
