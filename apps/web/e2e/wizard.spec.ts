import {expect, test, type Page} from '@playwright/test';

const CEO = /best return on marketing investment/i;

async function signIn(page: Page, id: string) {
  await page.goto('/');
  await page.getByTestId(`login-${id}`).click();
  await expect(page.getByTestId('synthetic-banner')).toBeVisible();
}

test('executive question streams real tool activity, cites evidence and reopens as a dated report', async ({page, context}) => {
  await signIn(page, 'u-ceo');
  await expect(page.getByTestId('runtime')).toContainText('REPLAY');
  await page.getByTestId('suggestion').filter({hasText: CEO}).click();
  const card = page.getByTestId('run-card').first();
  await expect(card.getByTestId('timeline')).toBeVisible();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(card.getByTestId('answer')).toContainText('not proven ROI');
  await expect(card.getByTestId('data-mode')).toHaveAttribute('data-mode', 'SYNTHETIC');
  await expect(card.getByTestId('check-status')).toHaveAttribute('data-status', 'NOT_CHECKED');
  await expect(card.getByTestId('visual')).toHaveCount(1);
  // The systems stage folds into a strip of the systems used; unfolded, NERP is done and its calls are listed.
  await expect(card.getByTestId('journey-system').filter({hasText: 'NERP'})).toBeVisible();
  await card.getByTestId('show-journey').click();
  const nerp = card.locator('[data-testid=stage-node][data-system=nerp]');
  await expect(nerp).toHaveAttribute('data-state', 'done');
  await nerp.click();
  await expect(card.getByTestId('stage-calls')).toContainText('Read NERP');
  await card.getByTestId('timeline').getByRole('button').first().click();
  await expect(card.getByTestId('timeline-item').filter({hasText: 'Read NERP'})).toHaveAttribute('data-state', 'ok');

  await card.getByTestId('citation').first().click();
  const drawer = page.getByTestId('evidence-drawer');
  await expect(drawer.getByTestId('evidence').first()).toContainText('nerp-mkt-spend-quarterly');
  await expect(drawer).toContainText('SA');
  await page.keyboard.press('Escape');

  const href = await card.getByTestId('open-report').getAttribute('href');
  const report = await context.newPage();
  await report.goto(href!);
  await expect(report.getByTestId('report-page')).toContainText('Which market gave us the best return');
  await expect(report.getByTestId('data-mode').first()).toHaveAttribute('data-mode', 'SYNTHETIC');
  await report.reload();
  await expect(report.getByTestId('visual')).toHaveCount(1);
});

test('check my data asks for a recomputation and marks the original answer', async ({page}) => {
  await signIn(page, 'u-cfo');
  await page.getByTestId('suggestion').filter({hasText: CEO}).click();
  const first = page.getByTestId('run-card').first();
  await expect(first).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await first.getByTestId('check-my-data').click();
  const check = page.getByTestId('run-card').nth(1);
  await expect(check).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(check.getByTestId('check-panel')).toContainText('MATCH');
  await expect(first.getByTestId('check-status')).toHaveAttribute('data-status', 'CHECKED');
});

test('planner and conquest questions run, and the prompt-injection note is called out', async ({page}) => {
  await signIn(page, 'u-ceo');
  await page.getByTestId('suggestion').filter({hasText: /channel-stuffing/}).click();
  await expect(page.getByTestId('run-card').first()).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(page.getByTestId('answer').first()).toContainText('screening result');
  await page.getByLabel('Your question').fill('Where are we winning switchers from Apple and Xiaomi according to Smart Switch?');
  await page.getByLabel('Your question').press('Enter');
  const second = page.getByTestId('run-card').nth(1);
  await expect(second).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(second.getByTestId('answer')).toContainText('did not act on it');
});

test('another user cannot open a report link and sees only entitled sources', async ({page, browser}) => {
  await signIn(page, 'u-ceo');
  await page.getByTestId('suggestion').filter({hasText: CEO}).click();
  const card = page.getByTestId('run-card').first();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  const href = await card.getByTestId('open-report').getAttribute('href');

  const other = await browser.newContext();
  const director = await other.newPage();
  await signIn(director, 'u-dir-gulf');
  await director.goto(href!);
  await expect(director.getByTestId('report-error')).toHaveAttribute('data-status', '404');
  await director.goto('/');
  await director.getByTestId('tab-sources').click();
  await director.getByTestId('source-system').filter({hasText: 'ASAP'}).click();
  await expect(director.getByTestId('source-explorer')).not.toContainText('Finance (restricted)');
  await other.close();
});

test('keyboard users can ask a question and reach the actions', async ({page}) => {
  await signIn(page, 'u-planner');
  const box = page.getByLabel('Your question');
  await box.focus();
  await page.keyboard.type('Flag any model where sell-in is outpacing sell-out');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('run-card').first()).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  const sources = page.getByTestId('show-sources').first();
  await sources.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('evidence-drawer')).toBeVisible();
});

test('a file attached to a question is read first, then shown under the question', async ({page}) => {
  await signIn(page, 'u-ceo');
  await page.getByTestId('file-input').setInputFiles([
    {name: 'gulf markets.csv', mimeType: 'text/csv', buffer: Buffer.from('Market,Units\nEG,1200\nSA,4500\n')},
    {name: 'broken.pptx', mimeType: 'application/octet-stream', buffer: Buffer.from('not a deck')},
  ]);
  const files = page.getByTestId('pending-file');
  await expect(files.filter({hasText: 'gulf markets.csv'})).toHaveAttribute('data-state', 'ok');
  await expect(files.filter({hasText: 'broken.pptx'})).toHaveAttribute('data-state', 'failed');
  await page.getByRole('button', {name: 'Remove broken.pptx'}).click();
  await page.getByLabel('Your question').fill('Which market gave us the best return on marketing investment last quarter?');
  await page.getByLabel('Your question').press('Enter');
  await expect(page.getByTestId('sent-files')).toContainText('F1');
  await expect(page.getByTestId('sent-files')).toContainText('gulf markets.csv');
  await expect(page.getByTestId('pending-file')).toHaveCount(0);
  await expect(page.getByTestId('run-card').first()).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
});

test('Email opens an Outlook draft with the question, the answer, the time taken and the sources it cites', async ({page}) => {
  await signIn(page, 'u-ceo');
  await page.getByTestId('suggestion').filter({hasText: CEO}).click();
  const card = page.getByTestId('run-card').first();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  const sent: {subject: string; html: string}[] = [];
  await page.route('**/api/v1/runs/*/email', async route => {  // never a real Outlook in tests
    sent.push(route.request().postDataJSON());
    await route.fulfill({json: {ok: true}});
  });
  await card.getByTestId('email-answer').click();
  await expect(page.getByRole('status').filter({hasText: 'open in Outlook as a draft'})).toBeVisible();
  expect(sent).toHaveLength(1);
  expect(sent[0].subject).toMatch(/^Wizard: Which market gave us the best return/);
  expect(sent[0].html).toContain('Answered by Wizard in');
  expect(sent[0].html).toContain('not proven ROI');
  expect(sent[0].html).toMatch(/<b>NERP › Marketing<\/b> [^<]+ <span[^>]*>\(E\d/);  // the report's module
  expect(sent[0].html).toContain('Synthetic data');

  await page.unroute('**/api/v1/runs/*/email');
  await page.route('**/api/v1/runs/*/email', route => route.fulfill({status: 503, json: {error: 'Outlook could not open a draft.', code: 'outlook_unavailable'}}));
  const download = page.waitForEvent('download');
  await card.getByTestId('email-answer').click();
  expect((await download).suggestedFilename()).toMatch(/^Wizard - Which market gave us the best return.*\.eml$/);
  await expect(page.getByRole('status').filter({hasText: 'downloaded instead'})).toBeVisible();
});

test('the compact desktop view answers and tells its Windows host what happened', async ({page}) => {
  // WizardBar hosts /quick in WebView2: stand in for window.chrome.webview and record what the page sends.
  await page.addInitScript(() => {
    const sent: unknown[] = [];
    const listeners: ((event: {data: unknown}) => void)[] = [];
    Object.assign(window, {
      __sent: sent,
      __fromHost: (data: unknown) => listeners.forEach(listener => listener({data})),
      chrome: {webview: {postMessage: (message: unknown) => sent.push(message),
        postMessageWithAdditionalObjects: (message: object, files: ArrayLike<File>) => sent.push({...message, files: Array.from(files, f => f.name)}),
        addEventListener: (_: string, listener: (event: {data: unknown}) => void) => listeners.push(listener), removeEventListener: () => undefined}},
    });
  });
  await signIn(page, 'u-ceo');
  await page.goto('/quick');
  await expect(page.getByTestId('quick-header')).toBeVisible();
  await page.getByTestId('suggestion').filter({hasText: CEO}).click();
  const card = page.getByTestId('run-card').first();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(card.getByTestId('answer')).toContainText('not proven ROI');
  const sent = await page.evaluate(() => (window as unknown as {__sent: unknown[]}).__sent);
  expect(sent).toContainEqual({type: 'busy', busy: true});
  expect(sent).toContainEqual(expect.objectContaining({type: 'finished', ok: true, question: expect.stringMatching(CEO)}));
  // The button acts out the run. In replay a tool returns in about 3 ms, too fast to be sure a frame shows it (the
  // tool-to-animation mapping is unit-tested); thinking and writing the answer last long enough to see every time.
  expect(sent).toContainEqual({type: 'activity', animation: 'think'});
  expect(sent).toContainEqual({type: 'activity', animation: 'write'});
  // A file dropped on the page goes to WizardBar with its place on disk; one dropped on the button comes back as attach.
  await page.evaluate(() => {
    const files = new DataTransfer();
    files.items.add(new File(['Market,Units\nEG,1\n'], 'sell-in.csv', {type: 'text/csv'}));
    window.dispatchEvent(new DragEvent('dragenter', {dataTransfer: files}));
  });
  await expect(page.getByTestId('drop-zone')).toContainText('Drop to attach');
  await page.evaluate(() => {
    const files = new DataTransfer();
    files.items.add(new File(['Market,Units\nEG,1\n'], 'sell-in.csv', {type: 'text/csv'}));
    window.dispatchEvent(new DragEvent('drop', {dataTransfer: files, cancelable: true}));
  });
  await expect(page.getByTestId('drop-zone')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as {__sent: unknown[]}).__sent.at(-1))).toEqual({type: 'drop', files: ['sell-in.csv']});
  await page.evaluate(() => (window as unknown as {__fromHost: (d: unknown) => void}).__fromHost(
    {type: 'attach', files: [{path: 'C:\\Users\\x\\scan.pdf', name: 'scan.pdf', error: 'PDF is not supported yet.'}]}));
  await expect(page.getByTestId('pending-file')).toHaveAttribute('data-state', 'failed');
  await expect(page.getByTestId('pending-file')).toContainText('scan.pdf');
  await page.keyboard.press('Escape');
  await expect.poll(() => page.evaluate(() => (window as unknown as {__sent: unknown[]}).__sent.at(-1))).toEqual({type: 'hide'});
  const full = await page.getByTestId('open-full').getAttribute('href');
  expect(full).toMatch(/^\/\?c=/);
  await page.goto(full!);
  await expect(page.getByTestId('run-card').first().getByTestId('answer')).toContainText('not proven ROI');
  await expect(page).toHaveURL(/\/$/);
});

test('the Brain page draws the knowledge base as a graph of communities and walks a presenter through it, beside the app', async ({page}) => {
  await signIn(page, 'u-ceo');
  await page.goto('/brain');
  await expect(page.getByTestId('brain-page')).toBeVisible();
  await expect(page.getByTestId('brain-examples')).toBeVisible();  // the synthetic notes are never shown as company knowledge
  await expect(page.getByTestId('brain-canvas')).toBeVisible();
  await expect(page.getByTestId('brain-page')).toHaveAttribute('data-dims', '2');
  await expect(page.getByTestId('brain-community').first()).toBeVisible();
  await expect(page.getByTestId('brain-select-all')).toBeChecked();
  await expect(page.locator('[data-testid=brain-system][data-system=asap]')).toContainText('reports');
  await expect(page.getByTestId('brain-stat').first()).toContainText('Nodes');
  await expect(page.getByTestId('brain-stats')).toContainText('Communities');
  await expect(page.getByTestId('brain-layout')).toContainText('settled', {timeout: 20_000});
  // Without a company database there is no news to show, and the page says why.
  await expect(page.getByTestId('news-missing')).toContainText('No company database');
  // A community can be hidden, and shown again with the rest.
  await page.getByTestId('brain-community-shown').first().uncheck();
  await expect(page.getByTestId('brain-select-all')).not.toBeChecked();
  await page.getByTestId('brain-select-all').check();
  await expect(page.getByTestId('brain-community-shown').first()).toBeChecked();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('brain-caption')).toContainText('Everything Wizard knows');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('brain-caption')).toContainText('Step 2');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('brain-caption')).toHaveCount(0);
  // Coloured by area instead, an area lights up.
  await page.getByTestId('brain-colour-area').click();
  await expect(page.getByTestId('brain-cluster').filter({hasText: 'Platforms'})).toBeVisible();
  await page.getByTestId('brain-cluster').filter({hasText: 'Metrics'}).click();
  await expect(page.getByTestId('brain-cluster').filter({hasText: 'Metrics'})).toHaveAttribute('aria-pressed', 'true');
  // Layers switch on and off; search finds a note and opens it with what it links to.
  const tags = page.locator('[data-testid=brain-layer][data-layer=tags]');
  await expect(tags).toBeChecked();
  await tags.uncheck();
  await expect(tags).not.toBeChecked();
  await page.getByTestId('brain-search').fill('GSCM platform');
  await expect(page.getByTestId('brain-results')).toContainText('GSCM platform guide');
  await page.getByTestId('brain-search').press('Enter');
  await expect(page.getByTestId('brain-card')).toContainText('GSCM platform guide');
  await expect(page.getByTestId('brain-neighbours')).toContainText('GSCM');
  await expect(page.getByTestId('brain-cluster').filter({hasText: 'Metrics'})).toHaveAttribute('aria-pressed', 'false');
  // The same graph in 3D.
  await page.getByTestId('brain-3d').click();
  await expect(page.getByTestId('brain-page')).toHaveAttribute('data-dims', '3');
  await expect(page.getByTestId('brain-rotate')).toBeVisible();
  await page.getByRole('link', {name: 'Ask Wizard'}).click();
  await expect(page.getByTestId('conversation-title')).toBeVisible();
});

test('on the Brain page, N plays a demo "new article came in" without moving any count', async ({page}) => {
  // A stand-in for the news table (replay mode has no company database).
  const latest = Array.from({length: 8}, (_, i) => ({title: `Headline ${i}`, category: i % 2 ? 'Competitors' : 'Smartphones',
    source: 'Wire', url: null, date: `2026-10-${String(20 - i).padStart(2, '0')}T08:00:00Z`}));
  await page.route('**/api/v1/brain/live', route => route.fulfill({json: {name: 'AI Team Database',
    database: {status: 'ok', relations: 12, schemas: 2},
    news: {status: 'ok', table: 'public.news', database: 'db', total: 1512, first: '2026-05-01', last: '2026-10-20T08:00:00Z',
      last_7_days: 0, categories: [{name: 'Competitors', count: 800}, {name: 'Smartphones', count: 712}],
      weekly: [{week: '2026-10-12', count: 30}, {week: '2026-10-19', count: 41}], latest, queries: ['SELECT 1'], data_mode: 'LIVE'}}}));
  await signIn(page, 'u-ceo');
  await page.goto('/brain');
  const panel = page.getByTestId('news-panel');
  await expect(panel.getByTestId('news-total')).toHaveText('1,512');
  await expect(panel.getByText('NEW', {exact: true})).toHaveCount(0);
  await page.keyboard.press('n');
  await expect(panel.getByTestId('news-arrived')).toContainText('1 new article just arrived');
  const first = panel.getByTestId('news-latest').locator('li').first();
  await expect(first).toContainText('Headline 3');
  await expect(first).toContainText('NEW');
  await expect(first).toContainText('just now');
  await expect(panel.getByTestId('news-latest').locator('li')).toHaveCount(8);  // moved to the top, not added
  await expect(panel.getByTestId('news-total')).toHaveText('1,512');
});

test('the roadmap shows what Wizard does, and the next Friday on each arrow key', async ({page}) => {
  await page.goto('/roadmap');
  await expect(page.getByTestId('roadmap-page')).toBeVisible();
  await expect(page.getByTestId('roadmap-capability').filter({hasText: 'Answers business questions'})).toBeVisible();
  await expect(page.getByTestId('roadmap-system').filter({hasText: 'ASAP'})).toBeVisible();
  await expect(page.getByTestId('roadmap-milestone')).toHaveCount(0);
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('roadmap-milestone')).toHaveCount(1);
  await expect(page.getByTestId('roadmap-milestone').first()).toContainText('SC+ Global Dashboard');
  await expect(page.getByTestId('roadmap-milestone').first()).toContainText('Fri 30 Oct');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('roadmap-milestone').nth(1)).toContainText('Weeks 2–3');
  await expect(page.getByTestId('roadmap-milestone').nth(1)).toContainText('PowerPoint');
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByTestId('roadmap-milestone')).toHaveCount(1);
  await page.keyboard.press('End');
  await expect(page.getByTestId('roadmap-milestone')).toHaveCount(3);
  await page.getByRole('link', {name: 'Ask Wizard'}).click();
  await expect(page).toHaveURL(/\/$/);
});

test('the systems picker limits a question to the systems ticked, and the conversation keeps them', async ({page}) => {
  await signIn(page, 'u-ceo');
  const picker = page.getByTestId('systems-picker');
  await expect(picker).toHaveAttribute('data-choice', 'auto');
  await picker.click();
  await page.locator('[data-testid=system-option][data-system=nerp]').click();
  await page.keyboard.press('Escape');
  // The knowledge base comes on with the first system ticked.
  await expect(picker).toHaveAttribute('data-choice', 'nerp,knowledge');
  await page.getByLabel('Your question').fill('Show the campaign notes for Egypt in Q3');
  await page.getByTestId('send').click();
  const card = page.getByTestId('run-card').first();
  await expect(card).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await expect(card.getByTestId('only-systems')).toHaveText('Only: NERP, Knowledge base');
  await page.reload();
  await expect(page.getByTestId('systems-picker')).toHaveAttribute('data-choice', 'nerp,knowledge');
  await page.getByTestId('systems-picker').click();
  await page.getByTestId('system-auto').click();
  await expect(page.getByTestId('systems-picker')).toHaveAttribute('data-choice', 'auto');
});

test('Not this on a step of a finished answer asks again, and Remember keeps a note for later questions', async ({page}) => {
  await signIn(page, 'u-cfo');
  await page.getByLabel('Your question').fill('Show the campaign notes for Egypt in Q3');
  await page.getByTestId('send').click();
  const first = page.getByTestId('run-card').first();
  await expect(first).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});
  await first.getByTestId('timeline').getByRole('button').first().click();
  await first.getByTestId('not-this').first().click();
  await first.getByRole('radio', {name: 'Wrong period'}).click();
  await first.getByLabel('What should Wizard use instead').fill('use Q2 2026');
  await first.getByTestId('not-this-send').click();
  await expect(page.getByTestId('user-turn').nth(1)).toContainText('Not this step: Read NERP');
  await expect(page.getByTestId('user-turn').nth(1)).toContainText('wrong period. use Q2 2026 Redo the answer.');
  await expect(page.getByTestId('run-card').nth(1)).toHaveAttribute('data-status', 'succeeded', {timeout: 30_000});

  await page.getByTestId('user-turn').first().hover();
  await page.getByTestId('remember').first().click();
  await page.getByLabel('What Wizard should remember').fill('Campaign notes: always show Egypt first.');
  await page.getByTestId('remember-form').getByRole('button', {name: 'Remember'}).click();
  await expect(page.getByTestId('remembered')).toBeVisible();
  await page.getByTestId('account-button').click();
  const notes = page.getByTestId('remembered-notes');
  await expect(notes.getByTestId('remembered-note')).toHaveText(['Campaign notes: always show Egypt first.']);
  await notes.getByRole('button', {name: 'Delete the note'}).click();
  await expect(notes.getByTestId('remembered-note')).toHaveCount(0);
});
