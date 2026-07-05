/**
 * Session-stop auto-review hook (Faza 4 Divergence Loop).
 *
 * Analizuje transkrypt sesji w poszukiwaniu divergence candidates:
 *   - Agent zaproponował → operator edytował → to divergence candidate
 *   - Szuka wzorców decyzji o regułach, propozycjach, edycjach operatora
 *   - Tworzy learning_rule_candidate z source: "auto_review"
 *
 * Called by .cursor/hooks.json "stop" hook.
 * Receives stdin JSON: { status, transcript_path, loop_count, conversation_id }
 */
const fs = require("fs");
const path = require("path");
const os = require("os");

const LOCK_FILE = path.join(os.tmpdir(), ".cursor-auto-review.lock");

// Wzorce sugerujące divergence candidate
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
  /edit|edyt/i,
  /hitl_edit|hitl_approve/i,
  /operator\s*response/i,
  /zatwierdz.*po edycji/i,
];

const RULE_DECISION_PATTERNS = [
  /uczymy.*się|uczymy.*sie|reguł|regul|rule.*candidate/i,
  /zatwierdz|odrzuc|approve|reject|rejected|approved/i,
  /playbook|pattern_key|candidate_id/i,
];

function findLatestTranscript() {
  const TRANSCRIPTS_DIR = path.join(os.tmpdir(), "cursor", "agent-transcripts");
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

function scanTranscript(filepath) {
  try {
    const content = fs.readFileSync(filepath, "utf8");
    const lower = content.toLowerCase();

    const proposals = [];
    const operatorEdits = [];
    const ruleDecisions = [];

    // Scan line by line for user turns mentioning divergence candidates
    const lines = content.split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      try {
        const obj = JSON.parse(line);
        if (obj.role !== "user") continue;
        const text = typeof obj.content === "string" ? obj.content : JSON.stringify(obj);

        for (const pat of PROPOSAL_PATTERNS) {
          if (pat.test(text)) {
            proposals.push(text.slice(0, 150));
            break;
          }
        }
        for (const pat of OPERATOR_EDIT_PATTERNS) {
          if (pat.test(text)) {
            operatorEdits.push(text.slice(0, 150));
            break;
          }
        }
        for (const pat of RULE_DECISION_PATTERNS) {
          if (pat.test(text)) {
            ruleDecisions.push(text.slice(0, 150));
            break;
          }
        }
      } catch { /* skip malformed */ }
    }

    return {
      proposals: [...new Set(proposals)].slice(0, 10),
      operatorEdits: [...new Set(operatorEdits)].slice(0, 10),
      ruleDecisions: [...new Set(ruleDecisions)].slice(0, 10),
      hasDivergenceActivity: proposals.length > 0 && operatorEdits.length > 0,
      totalCandidates: Math.min(proposals.length, operatorEdits.length),
    };
  } catch {
    return {
      proposals: [],
      operatorEdits: [],
      ruleDecisions: [],
      hasDivergenceActivity: false,
      totalCandidates: 0,
    };
  }
}

function formatSummary(scanResult) {
  if (!scanResult.hasDivergenceActivity) {
    return null;
  }

  const parts = [
    "--- AUTO-REVIEW: divergence candidates found ---",
    `Found ~${scanResult.totalCandidates} potential divergence candidate(s) in this session.`,
    "",
  ];

  if (scanResult.proposals.length > 0) {
    parts.push(`Proposals (${scanResult.proposals.length}):`);
    for (const p of scanResult.proposals.slice(0, 5)) {
      parts.push(`  \u2022 ${p.slice(0, 120)}`);
    }
    parts.push("");
  }

  if (scanResult.operatorEdits.length > 0) {
    parts.push(`Operator edits (${scanResult.operatorEdits.length}):`);
    for (const e of scanResult.operatorEdits.slice(0, 5)) {
      parts.push(`  \u2022 ${e.slice(0, 120)}`);
    }
    parts.push("");
  }

  if (scanResult.ruleDecisions.length > 0) {
    parts.push(`Rule decisions (${scanResult.ruleDecisions.length}):`);
    for (const d of scanResult.ruleDecisions.slice(0, 3)) {
      parts.push(`  \u2022 ${d.slice(0, 120)}`);
    }
    parts.push("");
  }

  parts.push(
    "ACTION REQUIRED:",
    "  For each divergence candidate found above, create a learning_rule_candidate",
    "  record in the database with source = 'auto_review' and status = 'pending_operator'.",
    "  Use the `update_candidate_status` or `maybe_create_learning_candidate` flow",
    "  to persist these so the operator can review them in the decision queue.",
    "",
    "  Format per candidate:",
    "    - pattern_key: <case_family>::<proposal_type>::<response_type>",
    "    - rule_text_pl: opis divergence ktora wymaga uwagi",
    "    - metadata: { \"source\": \"auto_review\", \"session\": \"<conversation_id>\" }",
  );

  return parts.join("\n");
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

    // Sentinel lock
    if (fs.existsSync(LOCK_FILE)) {
      process.stdout.write("{}\n");
      return;
    }

    // Only run on completed sessions
    if (status !== "completed") {
      process.stdout.write("{}\n");
      return;
    }

    // Prevent re-trigger loops
    if (loopCount > 0) {
      process.stdout.write("{}\n");
      return;
    }

    // Find transcript
    const resolvedPath = transcriptPath || findLatestTranscript();
    if (!resolvedPath || !fs.existsSync(resolvedPath)) {
      process.stdout.write("{}\n");
      return;
    }

    const result = scanTranscript(resolvedPath);
    const summary = formatSummary(result);

    // Write sentinel lock
    try { fs.writeFileSync(LOCK_FILE, new Date().toISOString(), "utf8"); } catch { }

    if (summary) {
      process.stdout.write(JSON.stringify({
        followup_message: summary,
        auto_review_found: result.totalCandidates,
        auto_review_session: convoId.slice(0, 12),
      }) + "\n");
    } else {
      process.stdout.write("{}\n");
    }
  } catch (err) {
    process.stdout.write(JSON.stringify({
      followup_message: "[AUTO-REVIEW ERROR] " + err.message,
    }) + "\n");
  }
});
