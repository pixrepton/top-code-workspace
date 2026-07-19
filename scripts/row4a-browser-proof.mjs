#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) continue;
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for ${key}`);
    }
    out[key.slice(2)] = value;
    i += 1;
  }
  return out;
}

function asText(value) {
  return String(value || '').trim();
}

function asList(value) {
  return Array.isArray(value) ? value.map((item) => asText(item)).filter(Boolean) : [];
}

async function writeJson(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function findExactDeskMembership(snapshot, expected) {
  const desk = Array.isArray(snapshot?.feed?.desk) ? snapshot.feed.desk : [];
  for (const row of desk) {
    if (!row || typeof row !== 'object') continue;
    const rowNoteId = asText(row.note_id || row.desk_note_id);
    const rowTitle = asText(row.title || row.title_pl);
    const rowMessageId = asText(row.source_message_id || row.message_id);
    const rowSignalIds = asList(row.source_signal_ids);
    const rowEngagementId = asText(row.engagement_id);
    const rowCaseId = asText(row.case_id);
    if (expected.messageId && rowMessageId !== expected.messageId) continue;
    if (expected.signalId && !rowSignalIds.includes(expected.signalId)) continue;
    if (expected.engagementId && rowEngagementId !== expected.engagementId) continue;
    if (expected.caseId && rowCaseId !== expected.caseId) continue;
    if (expected.noteId && rowNoteId !== expected.noteId) continue;
    return {
      found: true,
      card_id: rowNoteId,
      title: rowTitle,
      source_message_id: rowMessageId,
      source_signal_ids: rowSignalIds,
      engagement_id: rowEngagementId,
      case_id: rowCaseId,
    };
  }
  return {
    found: false,
    card_id: '',
    title: '',
    source_message_id: '',
    source_signal_ids: [],
    engagement_id: '',
    case_id: '',
  };
}

function expectedIdentityFromHandoffItem(item) {
  const traceId = asText(item.trace_id);
  return {
    messageId: asText(item.source_message_id || item.message_id),
    signalId: asText(item.signal_id),
    traceId: traceId || null,
    traceIdSource: traceId ? 'handoff.item.trace_id' : 'missing',
    engagementId: asText(item.engagement_id),
    caseId: asText(item.case_id),
    noteId: asText(item.note_id) || (asText(item.engagement_id) ? `desk-${asText(item.engagement_id)}` : ''),
    snapshotId: asText(item.snapshot_id),
    title: asText(item.title),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const proofDir = path.resolve(args['proof-dir'] || '');
  const handoffPath = path.resolve(args.handoff || '');
  const baseUrl = asText(args['base-url']);
  const login = asText(args.login);
  const password = asText(args.password);
  if (!proofDir || !handoffPath || !baseUrl || !login || !password) {
    throw new Error('Required args: --proof-dir --handoff --base-url --login --password');
  }

  const browserDir = path.join(proofDir, 'browser');
  const networkPath = path.join(browserDir, 'network.json');
  const consolePath = path.join(browserDir, 'console.json');
  const anchorsPath = path.join(browserDir, 'anchors.json');
  const exactMembershipPath = path.join(proofDir, 'exact-snapshot-membership.json');
  const beforeShot = path.join(browserDir, 'card-before-click.png');
  const detailShot = path.join(browserDir, 'detail-after-click.png');

  const handoff = JSON.parse(await fs.readFile(handoffPath, 'utf8'));
  if (handoff.actionable !== true || !handoff.item || typeof handoff.item !== 'object') {
    throw new Error('Handoff is not actionable.');
  }

  const item = handoff.item;
  const expected = expectedIdentityFromHandoffItem(item);

  const { firefox } = await import('playwright');
  const browser = await firefox.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const network = [];
  const consoleMessages = [];
  const pageErrors = [];
  const failedRequests = [];

  page.on('console', (msg) => {
    consoleMessages.push({
      type: msg.type(),
      text: msg.text(),
    });
  });
  page.on('pageerror', (err) => {
    pageErrors.push({
      name: err.name,
      message: err.message,
    });
  });
  page.on('requestfailed', (request) => {
    failedRequests.push({
      url: request.url(),
      method: request.method(),
      failure: request.failure(),
    });
  });
  page.on('response', async (response) => {
    const url = response.url();
    const entry = {
      url,
      status: response.status(),
      method: response.request().method(),
    };
    if (
      url.includes('/wp-json/daszek/v3/operational-feed-snapshots/latest') ||
      url.includes('/wp-json/daszek/v3/engagements/')
    ) {
      try {
        entry.body = await response.text();
      } catch (_error) {
        entry.body = '';
      }
    }
    network.push(entry);
  });

  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('#login-form input[name="login"]').fill(login);
    await page.locator('#login-form input[name="password"]').fill(password);

    const latestPromise = page.waitForResponse(
      (response) =>
        response.url().includes('/wp-json/daszek/v3/operational-feed-snapshots/latest') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 30000 },
    );

    await page.locator('#login-form button[type="submit"]').click();
    await page.waitForFunction(
      () => {
        const main = document.getElementById('main-screen');
        return !!main && window.getComputedStyle(main).display !== 'none';
      },
      null,
      { timeout: 30000 },
    );

    const skipButton = page.locator('#onboarding-skip');
    if ((await skipButton.count()) > 0) {
      try {
        if (await skipButton.first().isVisible()) {
          await skipButton.first().click();
        }
      } catch (_error) {
        // Ignore if onboarding is not shown.
      }
    }

    const latestResponse = await latestPromise;
    const latestPayload = await latestResponse.json();
    const latestSnapshot = latestPayload && typeof latestPayload === 'object' ? latestPayload.snapshot || {} : {};

    const membership = findExactDeskMembership(latestSnapshot, expected);
    if (!membership.found) {
      throw new Error('Exact snapshot membership not found for Row4a card.');
    }
    if (expected.snapshotId && asText(latestSnapshot.snapshot_id) !== expected.snapshotId) {
      throw new Error(`Latest snapshot mismatch. expected=${expected.snapshotId} actual=${asText(latestSnapshot.snapshot_id)}`);
    }

    await writeJson(exactMembershipPath, {
      proof_dir: proofDir,
      handoff_snapshot_id: expected.snapshotId,
      latest_snapshot_id: asText(latestSnapshot.snapshot_id),
      latest_matches_handoff_snapshot: asText(latestSnapshot.snapshot_id) === expected.snapshotId,
      expected_message_id: expected.messageId,
      expected_signal_id: expected.signalId,
      expected_engagement_id: expected.engagementId,
      expected_case_id: expected.caseId,
      expected_note_id: expected.noteId,
      expected_title: expected.title,
      membership_found: membership.found,
      membership: membership,
      latest_source_run_id: asText(latestSnapshot?.source?.source_run_id),
      latest_trigger_message_id: asText(latestSnapshot?.source?.trigger_message_id),
    });

    const cardSelector = `button.record-main[data-open-note="${membership.card_id}"]`;
    await page.waitForSelector(cardSelector, { timeout: 30000 });
    await page.screenshot({ path: beforeShot, fullPage: true });

    const liveResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/wp-json/daszek/v3/engagements/${encodeURIComponent(expected.engagementId)}/os-events`) &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 30000 },
    );

    await page.locator(cardSelector).click();
    const liveResponse = await liveResponsePromise;
    const liveBody = await liveResponse.json();

    await page.waitForSelector('.detail-section-os-events .os-event-row', { timeout: 30000 });
    await page.screenshot({ path: detailShot, fullPage: true });

    const detailText = await page.locator('#detail-panel').innerText();
    const anchors = {
      proof_dir: proofDir,
      page_url: baseUrl,
      message_id: expected.messageId,
      signal_id: expected.signalId,
      trace_id: expected.traceId,
      trace_id_source: expected.traceIdSource,
      engagement_id: expected.engagementId,
      case_id: expected.caseId,
      note_id: membership.card_id,
      snapshot_id: expected.snapshotId,
      handoff_title: expected.title,
      latest_snapshot_id: asText(latestSnapshot.snapshot_id),
      latest_title: membership.title,
      latest_source_signal_ids: membership.source_signal_ids,
      latest_trigger_message_id: asText(latestSnapshot?.source?.trigger_message_id),
      live_request_url: liveResponse.url(),
      live_request_status: liveResponse.status(),
      live_response_ok: Boolean(liveBody && liveBody.ok),
      live_response_engagement_id: asText(liveBody && liveBody.engagement_id),
      live_response_items_count: Array.isArray(liveBody && liveBody.items) ? liveBody.items.length : 0,
      latest_matches_handoff_snapshot: asText(latestSnapshot.snapshot_id) === expected.snapshotId,
      latest_matches_signal: membership.source_signal_ids.includes(expected.signalId),
      latest_title_matches_handoff: membership.title === expected.title,
      detail_contains_latest_title: detailText.includes(membership.title),
      js_errors: pageErrors.length,
      failed_requests: failedRequests.length,
    };

    await writeJson(anchorsPath, anchors);
    await writeJson(networkPath, network);
    await writeJson(consolePath, {
      console: consoleMessages,
      pageErrors,
      requestsFailed: failedRequests,
    });
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch(async (error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
