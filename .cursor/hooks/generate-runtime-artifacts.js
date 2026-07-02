/**
 * Generate Runtime Artifacts from Codebase Memory.
 *
 * Reads current state from CBM and regenerates API_INGRESS.md, DATABASE_OWNERSHIP.md,
 * FEATURE_FLAGS.md, and other artifacts in knowledge/runtime/.
 *
 * Usage: node .cursor/hooks/generate-runtime-artifacts.js
 *
 * Note: This script is a CI/periodic task. Run after major changes.
 * The Cursor MCP integration will call appropriate CBM queries
 * and regenerate the markdown files.
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const RUNTIME_DIR = path.join(__dirname, "..", "..", "knowledge", "runtime");
const CHANGELOG_PATH = path.join(RUNTIME_DIR, "CHANGELOG.md");
const LAST_REFRESHED_PATH = path.join(RUNTIME_DIR, ".last-refreshed");

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function getGitDiff() {
  try {
    const result = execSync('git diff --name-only HEAD', { encoding: 'utf8', cwd: path.join(__dirname, '..', '..') });
    return result.split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function writeTimestamp() {
  const now = new Date().toISOString();
  fs.writeFileSync(LAST_REFRESHED_PATH, now, 'utf8');
  console.log(`Last refreshed: ${now}`);
}

function updateChangelog(entries) {
  ensureDir(RUNTIME_DIR);
  const header = '# Architecture Drift Changelog\n\n> Auto-generated. Records changes detected between CBM graph and runtime artifacts.\n\n';
  const existing = fs.existsSync(CHANGELOG_PATH) ? fs.readFileSync(CHANGELOG_PATH, 'utf8') : header;
  const date = new Date().toISOString().split('T')[0];
  const newEntries = entries.map(e => `- ${date}: ${e}`).join('\n');

  if (entries.length > 0) {
    const content = `${header}\n## ${date}\n\n${newEntries}\n\n---\n\n${existing.replace(header, '')}`;
    fs.writeFileSync(CHANGELOG_PATH, content, 'utf8');
    console.log(`Changelog updated with ${entries.length} entries.`);
  } else {
    console.log('No drift detected. Changelog not updated.');
  }
}

// Main
function main() {
  ensureDir(RUNTIME_DIR);

  const changedFiles = getGitDiff();
  const relevantExtensions = ['.py', '.yml', '.yaml', '.env', '.env.example', '.sql'];
  const relevantChanges = changedFiles.filter(f =>
    relevantExtensions.some(ext => f.endsWith(ext))
  );

  if (relevantChanges.length === 0) {
    console.log('No relevant changes detected. Artifacts are current.');
    writeTimestamp();
    return;
  }

  console.log(`Detected ${relevantChanges.length} relevant file changes.`);
  console.log('To regenerate artifacts, run via Cursor with MCP queries:');
  console.log('  1. CBM: list_projects -> get_architecture -> query_graph');
  console.log('  2. Write results to knowledge/runtime/API_INGRESS.md');
  console.log('  3. Write results to knowledge/runtime/DATABASE_OWNERSHIP.md');
  console.log('  4. Write results to knowledge/runtime/FEATURE_FLAGS.md');

  updateChangelog([`${relevantChanges.length} files changed — artifacts may need regeneration.`]);
  writeTimestamp();
}

main();
