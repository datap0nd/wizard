// Chooses the person's saved option in a portal's own drop-down (not a select element) on an access request form, in
// Wizard's visible browser window. portal_fill.js marks the drop-down data-wizard-pick; portal_browser.py clicks it open,
// types the answer into the list's search box when the option is not shown, and clicks the matching option. This script
// only finds and marks what those clicks may touch: the drop-down itself and an option of the list it opened, never a
// button, a link or anything that submits.
// args: {mode: 'before' | 'options' | 'search' | 'state' | 'clear', mark, value}
//   before: mark the options already on the page, so the list the drop-down opens is told apart from them
//   options: the best option for value among those that appeared, marked data-wizard-option: {found, text, count, open}
//   search: the list's search box (where the focus went, in the drop-down, or in the list), marked data-wizard-search
//   state: {empty, text}: whether the drop-down still shows no choice
(args) => {
  const clean = s => String(s || '').replace(/[*：:]+\s*$/, '').replace(/\s+/g, ' ').trim();
  const norm = s => clean(s).replace(/[*：:()[\]]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const shown = el => (el.offsetParent !== null || el.getClientRects().length > 0) && getComputedStyle(el).visibility !== 'hidden';
  const textOf = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const fieldsIn = el => [...el.querySelectorAll('input, select, textarea')].filter(c => c.type !== 'hidden' && shown(c));
  const forbidden = el => el.closest('a[href]:not([href="#"]):not([href^="javascript:" i]), button:not([type="button"]), ' +
    'input[type="submit"], input[type="image"], input[type="reset"], #wizard-access-banner');
  const control = document.querySelector(`[data-wizard-pick="${CSS.escape(String(args.mark || ''))}"]`);
  const OPTIONISH = '[role="option"], [role="menuitem"], [role="treeitem"], li, [class*="option" i], [class*="item" i]';
  const options = () => {
    const all = [...document.querySelectorAll(OPTIONISH)].filter(el => shown(el) && !el.hasAttribute('data-wizard-seen')
      && !forbidden(el) && !fieldsIn(el).length && textOf(el) && textOf(el).length <= 300);
    const leaves = all.filter(el => !all.some(other => other !== el && el.contains(other)));
    const roles = leaves.filter(el => el.closest('[role="option"], [role="listbox"]'));
    return roles.length ? roles : leaves;
  };
  const editable = el => el && el.matches('input:not([type]), input[type="text"], input[type="search"]') && !el.readOnly
    && !el.disabled && shown(el) && !forbidden(el);
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

  if (args.mode === 'clear') {
    for (const name of ['data-wizard-seen', 'data-wizard-option', 'data-wizard-search']) {
      for (const el of document.querySelectorAll(`[${name}]`)) el.removeAttribute(name);
    }
    return true;
  }
  if (!control) return null;
  if (args.mode === 'before') {
    for (const el of document.querySelectorAll(OPTIONISH)) if (shown(el)) el.setAttribute('data-wizard-seen', '');
    return true;
  }
  if (args.mode === 'state') return {empty: dropEmpty(control), text: textOf(control) || (fieldsIn(control)[0] || control).value || ''};
  if (args.mode === 'search') {
    for (const old of document.querySelectorAll('[data-wizard-search]')) old.removeAttribute('data-wizard-search');
    // The drop-down's own search box, or one in the list it opened (outside the form, so never another field).
    const POPUP = '[role="listbox"], [role="dialog"], [class*="dropdown" i], [class*="popup" i], [class*="popper" i], [class*="menu" i], [class*="select" i]';
    const inList = el => editable(el) && !el.closest('form, [data-wizard-seen]') && !!el.closest(POPUP);
    const focused = document.activeElement;
    const box = [control, ...fieldsIn(control)].find(editable)
      || (focused && (control.contains(focused) ? editable(focused) : inList(focused)) ? focused : null)
      || [...document.querySelectorAll('input')].find(inList);
    if (!box) return false;
    box.setAttribute('data-wizard-search', '');
    return true;
  }
  if (args.mode === 'options') {
    for (const old of document.querySelectorAll('[data-wizard-option]')) old.removeAttribute('data-wizard-option');
    const list = options();
    const scored = list.map((el, i) => ({el, s: optionScore(textOf(el), args.value, i)}));
    const best = Math.max(0, ...scored.map(x => x.s));
    const top = scored.filter(x => x.s === best);
    // Several options that only contain the answer are a guess: leave the choice to the person.
    if (!best || (best < 3 && top.length > 1)) return {found: false, count: list.length, open: list.length > 0, several: top.length > 1 && best > 0};
    top[0].el.setAttribute('data-wizard-option', '');
    return {found: true, text: textOf(top[0].el), count: list.length, open: true};
  }
  return null;
}
