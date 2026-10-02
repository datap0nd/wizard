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
