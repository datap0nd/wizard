// Fills the person's saved answers into a portal's access request form, in Wizard's visible browser window
// (access_requests.py). It writes into empty fields only and never clicks a button, presses a key or submits a form:
// the person checks every field and submits the request themselves.
// args: {answers: [{label, value}], done: [labels already filled on this page]}
// returns {seen: [the form's field labels], filled: [labels filled now], kept: [labels whose field already had a value],
//          filled_total: n, missing: [labels without a field]}
(args) => {
  const clean = s => String(s || '').replace(/[*：:]+\s*$/, '').replace(/\s+/g, ' ').trim();
  const norm = s => clean(s).replace(/[*：:()[\]]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const shown = el => (el.offsetParent !== null || el.getClientRects().length > 0) && getComputedStyle(el).visibility !== 'hidden';
  const textOf = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const SKIP = new Set(['hidden', 'submit', 'button', 'reset', 'image', 'file', 'password', 'color', 'range']);
  const all = [...document.querySelectorAll('input, textarea, select')]
    .filter(el => !SKIP.has((el.type || '').toLowerCase()) && !el.disabled && !el.readOnly && shown(el));
  // A request form sits in a form or a dialog; a page's own search box outside them is not part of it.
  const inForm = all.filter(el => el.closest('form, dialog, [role="dialog"], [aria-modal="true"], [class*="modal" i], [class*="drawer" i]'));
  const controls = inForm.length ? inForm : all;

  const ownText = label => [...label.childNodes]
    .filter(n => !(n.nodeType === 1 && n.matches('input, select, textarea, option')))
    .map(n => n.textContent || '').join(' ');
  const LABELISH = 'label, legend, th, dt, [class*="label" i], [class*="title" i]';
  function labelsOf(el) {
    const found = [];
    const add = text => { const t = clean(text); if (t && t.length <= 160 && !found.some(f => norm(f) === norm(t))) found.push(t); };
    add(el.getAttribute('aria-label'));
    for (const id of (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)) add(textOf(document.getElementById(id)));
    if (el.id) for (const label of document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`)) add(ownText(label));
    const wrapping = el.closest('label');
    if (wrapping) add(ownText(wrapping));
    const group = el.closest('fieldset');
    if (group && (el.type === 'radio')) add(textOf(group.querySelector('legend')));
    // The field's own group (a row, a form item): only when it holds this one field, so another field's label is
    // never borrowed.
    const box = el.parentElement && el.parentElement.closest('tr, li, dd, [class*="form-item" i], [class*="formitem" i], ' +
      '[class*="form-group" i], [class*="field" i], [class*="control" i]');
    const alone = box && [...box.querySelectorAll('input, select, textarea')]
      .filter(c => c.type !== 'hidden' && !(el.type === 'radio' && c.type === 'radio' && c.name === el.name)).length <= 1;
    if (box && alone) {
      const named = [...box.querySelectorAll(LABELISH)].find(n => !n.contains(el) && textOf(n));
      if (named) add(textOf(named));
      else if (box.matches('tr')) add(textOf(box.querySelector('td')));
    }
    const before = el.previousElementSibling || (el.parentElement && el.parentElement.previousElementSibling);
    if (before && !before.matches('input, select, textarea') && textOf(before).length <= 80) add(textOf(before));
    add(el.getAttribute('placeholder'));
    add((el.getAttribute('name') || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' '));
    return found;
  }
  const described = controls.map(el => ({el, labels: labelsOf(el)}));

  function score(labels, wanted) {
    let best = 0;
    for (const label of labels.map(norm)) {
      if (label === wanted) return 3;
      if (label.startsWith(wanted + ' ') || wanted.startsWith(label + ' ')) best = Math.max(best, 2);
      else if (wanted.length >= 4 && (' ' + label + ' ').includes(' ' + wanted + ' ')) best = Math.max(best, 1);
    }
    return best;
  }
  const empty = el => el.type === 'checkbox' ? !el.checked
    : el.type === 'radio' ? !document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]:checked`).length
    : el.tagName === 'SELECT' ? (el.selectedIndex <= 0 || !el.value) : !el.value;
  function setValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new FocusEvent('blur'));
  }
  function fill(el, value) {
    if (el.tagName === 'SELECT') {
      const options = [...el.options];
      const option = options.find(o => norm(o.text) === norm(value) || norm(o.value) === norm(value))
        || options.find(o => norm(value).length >= 3 && norm(o.text).includes(norm(value)));
      if (!option) return false;
      setValue(el, option.value);
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

  const done = new Set((args.done || []).map(norm));
  const used = new Set();
  const filled = [];
  const kept = [];
  const missing = [];
  for (const answer of args.answers || []) {
    const wanted = norm(answer.label);
    if (!wanted || !String(answer.value || '').trim() || done.has(wanted)) continue;
    let best = null;
    for (const item of described) {
      if (used.has(item.el)) continue;
      const s = score(item.labels, wanted);
      if (s > 0 && (!best || s > best.score)) best = {item, score: s};
    }
    if (!best) { missing.push(answer.label); continue; }
    used.add(best.item.el);
    if (!empty(best.item.el)) { kept.push(answer.label); continue; }  // the person, or the form, filled it already
    if (fill(best.item.el, String(answer.value))) {
      filled.push(answer.label);
      best.item.el.style.outline = '2px solid #6d4aff';
      best.item.el.style.outlineOffset = '1px';
      if (!best.item.el.title) best.item.el.title = 'Filled by Wizard from your saved answers';
    }
  }

  const total = done.size + filled.length;
  if (total) {
    let banner = document.getElementById('wizard-access-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'wizard-access-banner';
      banner.setAttribute('role', 'status');
      banner.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:360px;padding:12px 14px;' +
        'border-radius:10px;background:#1f1640;color:#fff;font:13px/1.45 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25)';
      document.body.appendChild(banner);
    }
    banner.textContent = `Wizard filled ${total} field${total === 1 ? '' : 's'} from your saved answers (outlined). ` +
      'Check every field, then submit the request yourself: Wizard never submits it.';
  }
  // The form's labels, to offer in the settings: only from a form or dialog, or a page where an answer found its field
  // (not a catalog's search box).
  const seen = [];
  for (const item of inForm.length || used.size ? described : []) {
    const label = item.labels[0];
    if (label && !seen.includes(label) && seen.length < 60) seen.push(label);
  }
  return {seen, filled, kept, filled_total: total, missing};
}
