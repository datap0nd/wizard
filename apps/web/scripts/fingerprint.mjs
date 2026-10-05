// Source fingerprint of the compiled web app (same scheme as B2B): sha256 over src/, index.html, configs and the lockfile.
// `write` stores it in dist/.fingerprint next to the built assets; `check` verifies the committed dist matches the source,
// so a work PC (which never builds) always gets the web app that matches its code.
import {createHash} from 'node:crypto';
import {existsSync, readdirSync, readFileSync, statSync, writeFileSync} from 'node:fs';
import {join, relative, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const dist = join(root, 'dist');
const inputs = ['index.html', 'package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json'];

function walk(dir, out) {
  for (const entry of readdirSync(dir).sort()) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out); else if (!/\.test\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

export function fingerprint() {
  const hash = createHash('sha256');
  const files = [...inputs.map(f => join(root, f)).filter(existsSync), ...walk(join(root, 'src'), [])];
  // Line endings normalised so a Windows checkout (CRLF) and a CI checkout (LF) fingerprint identically.
  for (const file of files) { hash.update(relative(root, file).split(sep).join('/') + '\n'); hash.update(readFileSync(file, 'utf8').replaceAll('\r\n', '\n')); hash.update('\n'); }
  return 'sha256:' + hash.digest('hex');
}

// Utility classes the app always uses. A Tailwind build that could not scan the sources (e.g. the WASM fallback on a PC
// where the native binary is blocked) still "succeeds" but emits a stylesheet without them: an unstyled app.
const SENTINELS = ['.bg-page', '.text-ink-3', '.rounded-card', '.border-line', '.shadow-card', '.max-w-\\[820px\\]'];

function stylesheetProblems() {
  const assets = join(dist, 'assets');
  const css = existsSync(assets) ? readdirSync(assets).filter(f => f.endsWith('.css')) : [];
  if (css.length === 0) return ['no stylesheet in dist/assets'];
  const text = css.map(f => readFileSync(join(assets, f), 'utf8')).join('\n');
  return SENTINELS.filter(s => !text.includes(s)).map(s => `stylesheet lacks ${s}`);
}

const mode = process.argv[2];
if (mode === 'write') {
  const problems = stylesheetProblems();
  if (problems.length) { console.error(`Refusing to fingerprint a broken build (Tailwind did not scan the sources): ${problems.join('; ')}`); process.exit(1); }
  writeFileSync(join(dist, '.fingerprint'), fingerprint() + '\n');
  console.log('web app fingerprint written:', fingerprint());
} else if (mode === 'check') {
  const stored = existsSync(join(dist, '.fingerprint')) ? readFileSync(join(dist, '.fingerprint'), 'utf8').trim() : '(missing)';
  const current = fingerprint();
  if (stored !== current) { console.error(`Committed web app is stale: dist/.fingerprint ${stored} != source ${current}. Run npm --prefix apps/web run build and commit apps/web/dist.`); process.exit(1); }
  const problems = stylesheetProblems();
  if (problems.length) { console.error(`Committed web app is unstyled: ${problems.join('; ')}. Rebuild with the native Tailwind binary (or take the CI web-dist artifact).`); process.exit(1); }
  console.log('committed web app matches its source:', current);
} else {
  console.log(fingerprint());
}
