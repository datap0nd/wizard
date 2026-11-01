// Fills the person's saved answers into a portal's access request form, in Wizard's visible browser window
// (access_requests.py). It writes into empty fields only and never clicks a button, presses a key or submits a form:
// the person checks every field and submits the request themselves. A portal's own drop-down (not a select element)
// is chosen by Wizard's pick step (portal_pick.js, driven from portal_browser.py): this script only finds it, marks it
// data-wizard-pick and hands it back under picks.
// args: {answers: [{label, value, section?, kind?}], done: [names already handled on this page],
//        filled_before: how many fields Wizard filled on this page before,
//        note: what the window says about reaching the table and opening its form,
//        queue: {position, total, waiting, tables} | null (the window walks through the prepared requests)}
//   A name is "Section › Label", or the label alone. kind: 'text' (typed) or 'choice' (a drop-down); none: either.
// returns {seen: [the form's field labels], filled: [names filled now], kept: [names whose field already had a value],
//          filled_total: n, missing: [names without a field], picks: [{name, mark, value, typing}], next: bool}
(args) => {
  const clean = s => String(s || '').replace(/[*：:]+\s*$/, '').replace(/\s+/g, ' ').trim();
  const norm = s => clean(s).replace(/[*：:()[\]]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const shown = el => (el.offsetParent !== null || el.getClientRects().length > 0) && getComputedStyle(el).visibility !== 'hidden';
  const textOf = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const classOf = el => (typeof el.className === 'string' ? el.className : el.getAttribute('class')) || '';
  const SKIP = new Set(['hidden', 'submit', 'button', 'reset', 'image', 'file', 'password', 'color', 'range']);
  const fieldsIn = el => [...el.querySelectorAll('input, select, textarea')].filter(c => c.type !== 'hidden' && shown(c));
  const nameOf = a => (clean(a.section) ? `${clean(a.section)} › ` : '') + clean(a.label);
  for (const old of document.querySelectorAll('[data-wizard-pick]')) old.removeAttribute('data-wizard-pick');

  // A portal's own drop-down: a combobox, a list-box trigger, a read-only input, or a small box whose class names a
  // select, dropdown, combo or picker. Its root is its outermost such box holding at most one field.
  const DROPISH = /(^|[^a-z])(multi)?(select|dropdown|combo|combobox|picker)(box|field|input|wrapper|control|container|trigger|toggle)?([^a-z]|$)/i;
  const LISTISH = '[role="listbox"], [role="menu"], [role="option"], [role="tree"], option, datalist';
  const dropish = el => el.matches('[role="combobox"], [aria-haspopup="listbox"], [aria-haspopup="true"]') || DROPISH.test(classOf(el));
  function dropRoot(seed) {
    let root = dropish(seed) || (seed.tagName === 'INPUT' && seed.readOnly) ? seed : null;
    let el = seed.parentElement;
    for (let depth = 0; el && depth < 4; depth++, el = el.parentElement) {
      if (el.matches('form, body, dialog, [role="dialog"], fieldset')) break;
      if (el.getBoundingClientRect().height > 120 || fieldsIn(el).length > 1 || el.querySelector('textarea, select')) break;
      if (dropish(el)) root = el;
    }
    return root;
  }
  const forbidden = el => el.closest('a[href]:not([href="#"]):not([href^="javascript:" i]), button:not([type="button"]), ' +
    'input[type="submit"], input[type="image"], input[type="reset"]');
  const roots = [];
  const SEEDS = '[role="combobox"], [aria-haspopup="listbox"], [aria-haspopup="true"], input[readonly], [class*="select" i], ' +
    '[class*="dropdown" i], [class*="combo" i], [class*="picker" i]';
  for (const seed of document.querySelectorAll(SEEDS)) {
    if (seed.matches('select, option, textarea') || seed.closest(LISTISH) || seed.disabled || !shown(seed)) continue;
    if (seed.tagName === 'INPUT' && SKIP.has((seed.type || '').toLowerCase())) continue;
    const root = dropRoot(seed);
    if (!root || roots.includes(root) || forbidden(root) || root.closest('#wizard-access-banner')) continue;
    if (root.querySelector('a[href]:not([href="#"]):not([href^="javascript:" i]), button:not([type="button"]), ' +
      'input[type="submit"], input[type="image"], input[type="reset"]')) continue;  // a click on it could hit one
    const box = root.getBoundingClientRect();
    if (box.height > 120 || box.width < 30 || fieldsIn(root).length > 1 || root.querySelector('textarea, select')) continue;
    if (root.querySelectorAll('[role="option"], li').length > 1) continue;  // an open list, not its trigger
    roots.push(root);
  }
  const dropRoots = roots.filter(r => !roots.some(o => o !== r && o.contains(r)));
  const inDrop = el => dropRoots.some(r => r.contains(el));

  const typed = [...document.querySelectorAll('input, textarea, select')]
    .filter(el => !SKIP.has((el.type || '').toLowerCase()) && !el.disabled && !el.readOnly && shown(el) && !inDrop(el));
  const every = [...typed.map(el => ({el, type: el.tagName === 'SELECT' ? 'select' : 'text'})),
                 ...dropRoots.map(el => ({el, type: 'drop'}))];
  // A request form sits in a form or a dialog; a page's own search box outside them is not part of it.
  const FORMISH = 'form, dialog, [role="dialog"], [aria-modal="true"], [class*="modal" i], [class*="drawer" i]';
  const inForm = every.filter(c => c.el.closest(FORMISH));
  const controls = (inForm.length ? inForm : every)
    .sort((a, b) => (a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));

  const ownText = label => [...label.childNodes]
    .filter(n => !(n.nodeType === 1 && n.matches('input, select, textarea, option')))
    .map(n => n.textContent || '').join(' ');
  const LABELISH = 'label, legend, th, dt, [class*="label" i], [class*="title" i]';
  function labelsOf(el) {
    const found = [];
    const add = text => { const t = clean(text); if (t && t.length <= 160 && !found.some(f => norm(f) === norm(t))) found.push(t); };
    const inner = el.matches('input, select, textarea') ? null : fieldsIn(el)[0];
    for (const target of inner ? [el, inner] : [el]) {
      add(target.getAttribute('aria-label'));
      for (const id of (target.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)) add(textOf(document.getElementById(id)));
      if (target.id) for (const label of document.querySelectorAll(`label[for="${CSS.escape(target.id)}"]`)) add(ownText(label));
    }
    const wrapping = el.closest('label');
    if (wrapping) add(ownText(wrapping));
    const group = el.closest('fieldset');
    if (group && (el.type === 'radio')) add(textOf(group.querySelector('legend')));
    // The field's own group (a row, a form item): only when it holds this one field, so another field's label is
    // never borrowed.
    const box = el.parentElement && el.parentElement.closest('tr, li, dd, [class*="form-item" i], [class*="formitem" i], ' +
      '[class*="form-group" i], [class*="field" i], [class*="control" i]');
    const alone = box && !inDrop(box) && [...box.querySelectorAll('input, select, textarea')]
      .filter(c => c.type !== 'hidden' && !(el.type === 'radio' && c.type === 'radio' && c.name === el.name)).length <= 1;
    if (box && alone) {
      const named = [...box.querySelectorAll(LABELISH)].find(n => !n.contains(el) && !el.contains(n) && textOf(n));
      if (named) add(textOf(named));
      else if (box.matches('tr')) add(textOf(box.querySelector('td')));
    }
    // The nearest text above it: a sibling before it, or before a box around it, that holds no other field.
    let node = el;
    for (let depth = 0; node && depth < 4 && !node.matches('form, body, dialog'); depth++, node = node.parentElement) {
      let before = node.previousElementSibling;
      while (before && !textOf(before) && !fieldsIn(before).length) before = before.previousElementSibling;
      if (!before) continue;
      if (!fieldsIn(before).length && !dropRoots.some(r => before.contains(r)) && textOf(before).length <= 80) add(textOf(before));
      break;
    }
    for (const target of inner ? [el, inner] : [el]) add(target.getAttribute('placeholder'));
    const placeholder = el.matches('input, select, textarea') ? null : el.querySelector('[class*="placeholder" i]');
    if (placeholder) add(textOf(placeholder));
    for (const target of inner ? [el, inner] : [el]) {
      add((target.getAttribute('name') || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' '));
    }
    return found;
  }
  const described = controls.map(c => ({...c, labels: labelsOf(c.el)}));

  // A section is the box a field sits in (DPA / DSA): its heading comes before the field, in a box that holds both.
  const heads = new Map();
  function headsOf(section) {
    const wanted = norm(section);
    if (!heads.has(wanted)) {
      heads.set(wanted, [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, label, strong, b, p, span, div, th, dt, td')]
        .filter(h => (h.textContent || '').length <= wanted.length + 12 && !h.querySelector('input, select, textarea')
          && shown(h) && (n => n === wanted || (n.startsWith(wanted) && n.length <= wanted.length + 3))(norm(textOf(h)))));
    }
    return heads.get(wanted);
  }
  const inSection = (el, section) => headsOf(section).some(h => {
    if (!(h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) return false;
    let box = h.parentElement;
    for (let depth = 0; box && depth < 5 && !box.matches('body, html'); depth++, box = box.parentElement) {
      if (box.contains(el)) return true;
    }
    return false;
  });

  function score(labels, wanted) {
    let best = 0;
    for (const label of labels.map(norm)) {
      if (label === wanted) return 3;
      if (label.startsWith(wanted + ' ') || wanted.startsWith(label + ' ')) best = Math.max(best, 2);
      else if (wanted.length >= 4 && (' ' + label + ' ').includes(' ' + wanted + ' ')) best = Math.max(best, 1);
    }
    return best;
  }
  function dropEmpty(root) {
    const placeholder = root.querySelector('[class*="placeholder" i]');
    if (placeholder && shown(placeholder) && textOf(placeholder)) return true;
    const input = root.matches('input') ? root : fieldsIn(root)[0];
    if (input && input.value && input.value.trim()) return false;
    const text = textOf(root);
    if (!text.replace(/[^\p{L}\p{N}]+/gu, '')) return true;  // nothing but an icon (a magnifier, an arrow)
    if (input && norm(text) === norm(input.getAttribute('placeholder'))) return true;
    return /^(select|choose|search|please|pick|--|none)\b/i.test(text);
  }
  const empty = item => item.type === 'drop' ? dropEmpty(item.el)
    : item.el.type === 'checkbox' ? !item.el.checked
    : item.el.type === 'radio' ? !document.querySelectorAll(`input[type=radio][name="${CSS.escape(item.el.name)}"]:checked`).length
    : item.el.tagName === 'SELECT' ? (item.el.selectedIndex <= 0 || !item.el.value) : !item.el.value;
  function setValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new FocusEvent('blur'));
  }
  // An option's text against the answer: the same text, the same text without its number ("5. ..."), the number
  // alone, or the answer as whole words in it (a code such as SGE).
  function optionScore(text, value, index) {
    const t = norm(text), v = norm(value);
    if (!t || !v) return 0;
    const bare = t.replace(/^\d{1,3}\s*[.)]\s*/, '');
    if (t === v || bare === v) return 4;
    const number = /^\d{1,3}$/.test(v) ? Number(v) : null;
    const lead = t.match(/^(\d{1,3})\s*[.)]/);
    if (number !== null) return lead ? (Number(lead[1]) === number ? 4 : 0) : (index + 1 === number ? 3 : 0);
    if (v.length >= 2 && (' ' + t + ' ').includes(' ' + v + ' ')) return 2;
    return 0;
  }
  function fill(el, value) {
    if (el.tagName === 'SELECT') {
      const options = [...el.options].filter(o => o.value !== '' || o.index > 0);
      const scored = options.map((o, i) => ({o, s: Math.max(optionScore(o.text, value, i), norm(o.value) === norm(value) ? 4 : 0)}));
      const best = Math.max(0, ...scored.map(x => x.s));
      const top = scored.filter(x => x.s === best);
      if (!best || (best < 3 && top.length > 1)) return false;
      setValue(el, top[0].o.value);
      return true;
    }
    if (el.type === 'checkbox') {
      if (!/^(yes|true|1|on|x|checked|y)$/i.test(value.trim())) return false;
      el.checked = true;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    if (el.type === 'radio') {
      const choice = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)]
        .find(r => labelsOf(r).some(l => norm(l) === norm(value)) || norm(r.value) === norm(value));
      if (!choice) return false;
      choice.checked = true;
      choice.dispatchEvent(new Event('input', {bubbles: true}));
      choice.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
    setValue(el, value);
    return el.value === value;
  }
  const outline = el => {
    el.setAttribute('data-wizard-filled', '');
    el.style.outline = '2px solid #6d4aff';
    el.style.outlineOffset = '1px';
    if (!el.title) el.title = 'Filled by Wizard from your saved answers';
  };

  const answers = (args.answers || []).filter(a => norm(a.label) && String(a.value || '').trim());
  const sections = [...new Set(answers.map(a => clean(a.section)).filter(Boolean))];
  const done = new Set((args.done || []).map(norm));
  const used = new Set();
  const filled = [];
  const kept = [];
  const missing = [];
  const picks = [];
  for (const answer of answers) {
    const name = nameOf(answer);
    if (done.has(norm(name))) continue;
    const wanted = norm(answer.label);
    const fits = item => answer.kind === 'text' ? item.type === 'text'
      : answer.kind === 'choice' ? item.type !== 'text' || item.el.tagName === 'INPUT' : true;
    let candidates = described.filter(item => !used.has(item.el) && fits(item))
      .map(item => ({item, score: score(item.labels, wanted) + (answer.kind === 'choice' && item.type !== 'text' ? 0.25 : 0)}))
      .filter(c => c.score >= 1);
    if (clean(answer.section)) {
      const inside = candidates.filter(c => inSection(c.item.el, answer.section));
      if (inside.length) candidates = inside;
    } else if (sections.length) {
      const outside = candidates.filter(c => !sections.some(s => inSection(c.item.el, s)));
      if (outside.length) candidates = outside;
    }
    const best = candidates.reduce((top, c) => (!top || c.score > top.score ? c : top), null);
    if (!best) { missing.push(name); continue; }
    const item = best.item;
    used.add(item.el);
    if (!empty(item)) { kept.push(name); continue; }  // the person, or the form, filled it already
    if (item.type === 'drop' || (answer.kind === 'choice' && item.type === 'text')) {
      const mark = String(picks.length + 1);
      item.el.setAttribute('data-wizard-pick', mark);
      picks.push({name, mark, value: String(answer.value), typing: item.type === 'text'});
      continue;
    }
    if (fill(item.el, String(answer.value))) {
      filled.push(name);
      outline(item.el);
    }
  }

  // The note on the page: what Wizard filled, and with prepared requests, which one this is and the way to the next.
  const next = document.documentElement.getAttribute('data-wizard-next') === '1';
  if (next) document.documentElement.removeAttribute('data-wizard-next');
  const total = (args.filled_before || 0) + filled.length;
  const queue = args.queue || null;
  let banner = document.getElementById('wizard-access-banner');
  if ((total || queue || args.note) && !banner) {
    banner = document.createElement('div');
    banner.id = 'wizard-access-banner';
    banner.setAttribute('role', 'status');
    banner.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;max-width:380px;padding:12px 14px;' +
      'border-radius:10px;background:#1f1640;color:#fff;font:13px/1.45 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25)';
    document.body.appendChild(banner);
  }
  if (banner && !banner.hasAttribute('data-hidden')) {
    const lines = [];
    if (queue) {
      lines.push(`Prepared request ${queue.position} of ${queue.total}` + (queue.tables ? `: ${queue.tables}.` : '.') +
        (total ? '' : ' Press Request access on this page if the form is behind it; Wizard fills it as it appears.'));
    }
    if (args.note) lines.push(String(args.note));
    if (total) {
      lines.push(`Wizard filled ${total} field${total === 1 ? '' : 's'} from your saved answers (outlined). ` +
        'Check every field, then submit the request yourself: Wizard never submits it.');
    }
    const state = JSON.stringify([lines, queue && queue.waiting]);
    if (banner.getAttribute('data-state') !== state) {
      banner.setAttribute('data-state', state);
      banner.replaceChildren(...lines.map(line => Object.assign(document.createElement('p'), {textContent: line,
        style: 'margin:0 0 4px'})));
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:6px';
      const button = (label, act) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = label;
        b.style.cssText = 'font:inherit;border:0;border-radius:6px;padding:4px 10px;cursor:pointer;background:#6d4aff;color:#fff';
        b.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); act(); });
        return b;
      };
      if (queue && queue.waiting > 0) {
        row.appendChild(button(`Next request (${queue.waiting} to go)`, () => {
          document.documentElement.setAttribute('data-wizard-next', '1');
          banner.lastChild.firstChild.textContent = 'Opening the next request…';
        }));
      } else if (queue) {
        row.appendChild(Object.assign(document.createElement('span'), {textContent: 'That was the last prepared request.'}));
      }
      const hide = button('Hide', () => { banner.setAttribute('data-hidden', ''); banner.style.display = 'none'; });
      hide.style.background = 'transparent';
      hide.style.border = '1px solid rgba(255,255,255,.4)';
      row.appendChild(hide);
      banner.appendChild(row);
    }
  }
  // The form's labels, to offer in the settings: only from a form or dialog, or a page where an answer found its field
  // (not a catalog's search box).
  const seen = [];
  for (const item of inForm.length || used.size ? described : []) {
    const label = item.labels[0];
    if (label && !seen.includes(label) && seen.length < 60) seen.push(label);
  }
  return {seen, filled, kept, filled_total: total, missing, picks, next};
}
