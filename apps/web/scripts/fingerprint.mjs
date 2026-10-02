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

const mode = process.argv[2];
if (mode === 'write') {
  writeFileSync(join(dist, '.fingerprint'), fingerprint() + '\n');
  console.log('web app fingerprint written:', fingerprint());
} else if (mode === 'check') {
  const stored = existsSync(join(dist, '.fingerprint')) ? readFileSync(join(dist, '.fingerprint'), 'utf8').trim() : '(missing)';
  const current = fingerprint();
  if (stored !== current) { console.error(`Committed web app is stale: dist/.fingerprint ${stored} != source ${current}. Run npm --prefix apps/web run build and commit apps/web/dist.`); process.exit(1); }
  console.log('committed web app matches its source:', current);
} else {
  console.log(fingerprint());
}
