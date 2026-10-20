// Runs inside a portal page (every frame) for wizard_connectors.portal_browser. Read-only: it numbers what can be
// clicked or typed into (data-wizard-ref), reads visible text and finds tables. It never clicks, types or submits.
(args) => {
  const start = args.start, limit = args.limit, textLimit = args.textLimit;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity || 1) > 0.05;
  };
  const inView = el => {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };
  const labelOf = el => {
    const byId = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    const labelled = el.getAttribute('aria-labelledby');
    const fromIds = labelled ? labelled.split(/\s+/).map(id => clean(document.getElementById(id)?.innerText)).join(' ') : '';
    return clean(el.getAttribute('aria-label') || fromIds || (byId && byId.innerText) || el.getAttribute('title')
      || el.getAttribute('placeholder') || el.getAttribute('alt') || '');
  };
  const nameOf = el => {
    const tag = el.tagName.toLowerCase();
    const own = labelOf(el);
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return own.slice(0, 100);
    return (own || clean(el.innerText || el.textContent)).slice(0, 100);
  };
  const editor = el => !!el.closest('.ace_editor, .monaco-editor, .CodeMirror, .cm-editor, [data-mode="sql"]');
  const kindOf = el => {
    const tag = el.tagName.toLowerCase(), role = el.getAttribute('role') || '', type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'select' || role === 'combobox' || role === 'listbox') return tag === 'select' ? 'select' : 'combobox';
    if (tag === 'textarea') return editor(el) ? 'code-editor' : 'text';
    if (tag === 'input') {
      if (type === 'password') return 'password';
      if (type === 'file') return 'file';
      if (['checkbox', 'radio'].includes(type)) return type;
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      return 'text';
    }
    if (el.isContentEditable) return editor(el) ? 'code-editor' : 'rich-text';
    if (tag === 'a') return 'link';
    return role || (tag === 'button' || tag === 'summary' ? 'button' : 'clickable');
  };
  const sameHost = href => { try { return new URL(href, location.href).host === location.host; } catch { return false; } };
  const hrefOf = el => {
    const href = el.getAttribute('href');
    if (!href || href.startsWith('javascript:') || href === '#') return null;
    try {
      const url = new URL(href, location.href);
      return sameHost(href) ? url.pathname + url.search : url.host + url.pathname;
    } catch { return null; }
  };

  document.querySelectorAll('[data-wizard-ref]').forEach(e => e.removeAttribute('data-wizard-ref'));
  document.querySelectorAll('[data-wizard-table]').forEach(e => e.removeAttribute('data-wizard-table'));
  const selector = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [contenteditable=""], ' +
    '[contenteditable=true], [role=button], [role=link], [role=tab], [role=menuitem], [role=menuitemcheckbox], ' +
    '[role=menuitemradio], [role=treeitem], [role=option], [role=checkbox], [role=radio], [role=switch], ' +
    '[role=combobox], [role=listbox], [role=searchbox], [role=textbox], [onclick], [tabindex="0"]';
  const found = new Set(document.querySelectorAll(selector));
  // Portals draw many controls as plain elements with a pointer cursor; take the outermost such element.
  let scanned = 0;
  for (const el of document.querySelectorAll('div, span, li, td, img, svg, label, p')) {
    if (++scanned > 4000) break;
    if (getComputedStyle(el).cursor === 'pointer' && !(el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer')) {
      found.add(el);
    }
  }
  const insideLink = el => { const a = el.parentElement && el.parentElement.closest('a[href]'); return !!a && found.has(a); };
  const candidates = [...found].filter(el => shown(el) && !el.closest('[aria-hidden=true]') && !insideLink(el));
  candidates.sort((a, b) => (inView(b) - inView(a)) || (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));

  const elements = [];
  let ref = start;
  for (const el of candidates) {
    if (elements.length >= limit) break;
    const kind = kindOf(el), name = nameOf(el);
    if (!name && !['text', 'select', 'combobox', 'checkbox', 'radio'].includes(kind)) continue;
    el.setAttribute('data-wizard-ref', String(ref));
    const item = {ref, kind, name};
    const role = el.getAttribute('role');
    if (role) item.role = role;
    const href = el.tagName.toLowerCase() === 'a' ? hrefOf(el) : null;
    if (href) item.href = href;
    if (el.hasAttribute('download')) item.download = true;
    if (kind === 'text' || kind === 'combobox') item.value = clean(el.value || el.getAttribute('aria-valuetext') || '').slice(0, 80);
    if (kind === 'select') {
      item.value = clean(el.selectedOptions?.[0]?.text || '');
      item.options = [...el.options].slice(0, 30).map(o => clean(o.text)).filter(Boolean);
    }
    if (kind === 'checkbox' || kind === 'radio') item.checked = !!el.checked;
    const checked = el.getAttribute('aria-checked') || el.getAttribute('aria-selected');
    if (checked) item.selected = checked === 'true';
    const expanded = el.getAttribute('aria-expanded');
    if (expanded) item.expanded = expanded === 'true';
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') item.disabled = true;
    if (!inView(el)) item.below_or_above = true;
    elements.push(item);
    ref += 1;
  }

  const tables = [];
  for (const el of document.querySelectorAll('table, [role=grid], [role=table], [role=treegrid]')) {
    if (!shown(el) || el.parentElement?.closest('table, [role=grid], [role=table], [role=treegrid]')) continue;
    const rows = el.tagName === 'TABLE' ? el.rows.length : el.querySelectorAll('[role=row]').length;
    if (rows < 2) continue;
    el.setAttribute('data-wizard-table', String(ref));
    const caption = clean(el.querySelector('caption')?.innerText || el.getAttribute('aria-label') || '');
    const first = el.tagName === 'TABLE' ? el.rows[0] : el.querySelector('[role=row]');
    const headers = first ? [...first.children].slice(0, 15).map(c => clean(c.innerText).slice(0, 40)) : [];
    const declared = Number(el.getAttribute('aria-rowcount') || 0);
    tables.push({ref, caption: caption.slice(0, 100), rows_drawn: rows, rows_declared: declared || null, headers});
    ref += 1;
  }

  const passwordField = [...document.querySelectorAll('input[type=password]')].some(shown);
  const text = clean(document.body ? document.body.innerText : '').slice(0, textLimit);
  return {title: document.title || '', text, elements, tables, more: candidates.length > elements.length,
          next: ref, password_field: passwordField,
          scroll: {y: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight), view: innerHeight}};
}
