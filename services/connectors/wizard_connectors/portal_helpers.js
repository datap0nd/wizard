// Wizard's helpers for Gemini's portal scripts, available as W in every evaluate step. They carry what Metronome
// learned driving ASAP (MicroStrategy Web inside a portal shell) and GSCM (TOBESOFT Nexacro) into reusable calls, so a
// script reads data instead of rediscovering the portal. Every helper only reads; the browser refuses writes anyway.
const W = (() => {
  const W = {};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  W.sleep = sleep;

  // A value that survives the trip back to Wizard: no DOM nodes, functions or cycles, bounded size.
  W.plain = (value, depth = 0, seen = new WeakSet()) => {
    if (value === undefined) return null;
    if (value === null || typeof value === 'boolean' || typeof value === 'string') return value;
    if (typeof value === 'number') return Number.isFinite(value) ? value : String(value);
    if (typeof value === 'bigint') return value.toString();
    if (typeof value === 'function') return null;
    if (depth > 12) return '…';
    if (typeof Node !== 'undefined' && value instanceof Node) return W.describe(value);
    if (value instanceof Date) return value.toISOString();
    if (typeof value !== 'object') return String(value);
    if (seen.has(value)) return '(cycle)';
    seen.add(value);
    const listLike = Array.isArray(value) || (typeof NodeList !== 'undefined' && value instanceof NodeList) ||
      (typeof HTMLCollection !== 'undefined' && value instanceof HTMLCollection);
    if (listLike) return Array.from(value).slice(0, 100000).map(v => W.plain(v, depth + 1, seen));
    const out = {};
    let n = 0;
    for (const key of Object.keys(value)) {
      if (n++ > 500) { out['…'] = 'more keys'; break; }
      try { out[key] = W.plain(value[key], depth + 1, seen); } catch (e) { out[key] = '(unreadable)'; }
    }
    return out;
  };

  // A table ({columns, rows}: what W.nexacro.read, readGrid, bookmarks and menu return) as a list of row objects, to
  // filter or map in a script. Return the table itself to cite it.
  W.objects = table => (table && Array.isArray(table.rows) ? table.rows.map(r => Object.fromEntries((table.columns || []).map((c, i) => [c, r[i]]))) : []);

  W.text = el => (el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '');
  W.visible = el => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  W.describe = el => {
    if (!el || el.nodeType !== 1) return null;
    return {tag: el.tagName.toLowerCase(), id: el.id || undefined, text: W.text(el).slice(0, 120) || undefined,
            role: el.getAttribute('role') || undefined, name: el.getAttribute('name') || el.getAttribute('aria-label') || undefined};
  };
  W.waitFor = async (check, ms = 30000, every = 250) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      try { const value = await check(); if (value) return value; } catch (e) { /* not yet */ }
      await sleep(every);
    }
    throw new Error(`waited ${Math.round(ms / 1000)} s without the condition becoming true`);
  };
  W.fetchText = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'include', ...options});
    const text = await response.text();
    return {status: response.status, ok: response.ok, contentType: (response.headers.get('content-type') || '').split(';')[0], text};
  };
  W.fetchJson = async (url, options = {}) => {
    const result = await W.fetchText(url, {headers: {Accept: 'application/json', ...(options.headers || {})}, ...options});
    try { result.json = JSON.parse(result.text); } catch (e) { result.json = null; }
    delete result.text;
    return result;
  };

  // Tables on screen: an HTML table (or ARIA grid) as {columns, rows, total_rows}.
  W.readTable = (target = 'table', nth = 0) => {
    let el = target;
    if (typeof target === 'string') {
      const text = target.startsWith('text=') ? target.slice(5) : null;
      const found = text
        ? [...document.querySelectorAll('table, [role=grid]')].filter(t => W.text(t).includes(text))
        : [...document.querySelectorAll(target)];
      el = found.filter(W.visible)[nth] || found[nth];
    }
    if (!el) throw new Error(`no table matches ${String(target)}`);
    const table = el.matches('table, [role=grid]') ? el : el.querySelector('table, [role=grid]') || el;
    const rowEls = [...table.querySelectorAll('tr, [role=row]')];
    const grid = [];
    const spans = [];
    rowEls.forEach((tr, r) => {
      const cells = [...tr.children].filter(c => c.matches('td, th, [role=cell], [role=gridcell], [role=columnheader], [role=rowheader]'));
      const row = grid[r] = grid[r] || [];
      let c = 0;
      for (const cell of cells) {
        while (row[c] !== undefined) c++;
        const colspan = Math.min(Number(cell.getAttribute('colspan')) || 1, 50), rowspan = Math.min(Number(cell.getAttribute('rowspan')) || 1, 50);
        const value = W.text(cell);
        for (let dr = 0; dr < rowspan; dr++) for (let dc = 0; dc < colspan; dc++) {
          grid[r + dr] = grid[r + dr] || [];
          grid[r + dr][c + dc] = value;
        }
        if (cell.matches('th, [role=columnheader]')) spans[r] = true;
        c += colspan;
      }
    });
    // Header rows: the leading rows made of header cells; without any, the first row names the columns.
    let headerCount = 0;
    while (headerCount < grid.length && spans[headerCount]) headerCount++;
    headerCount = Math.max(1, headerCount);
    const width = Math.max(0, ...grid.map(r => (r ? r.length : 0)));
    const columns = [];
    for (let c = 0; c < width; c++) {
      const parts = [];
      for (let r = 0; r < headerCount; r++) { const v = grid[r] && grid[r][c]; if (v && parts[parts.length - 1] !== v) parts.push(v); }
      let name = parts.join(' / ') || `column_${c + 1}`;
      while (columns.includes(name)) name += '_';
      columns.push(name);
    }
    const rows = grid.slice(headerCount).filter(r => r && r.some(v => v !== '' && v !== undefined))
      .map(r => columns.map((_, c) => W.number(r[c])));
    return {columns, rows, total_rows: rows.length};
  };
  // "1,234.5" -> 1234.5, "(12)" -> -12, "12%" stays text; anything else unchanged.
  W.number = value => {
    if (typeof value !== 'string') return value === undefined ? null : value;
    const t = value.trim();
    if (!/^\(?-?[\d,]*\.?\d+\)?$/.test(t) || (t.includes(',') && !/^\(?-?\d{1,3}(,\d{3})*(\.\d+)?\)?$/.test(t))) return value;
    const n = Number(t.replace(/[(),]/g, ''));
    return Number.isFinite(n) ? (t.startsWith('(') ? -n : n) : value;
  };

  // What is on this page, for exploring: controls with a selector to click, tables, frames, text, and which portal
  // technology is present. Secrets are never included (W.mstr.session() reports only whether the session is signed in).
  W.look = (limit = 60) => {
    const controls = [];
    const seen = new Set();
    const selectorFor = el => {
      if (el.id && document.querySelectorAll(`[id="${CSS.escape(el.id)}"]`).length === 1) return `[id="${el.id}"]`;
      const name = el.getAttribute('name');
      if (name) return `${el.tagName.toLowerCase()}[name="${name}"]`;
      const text = W.text(el);
      if (text && text.length <= 60) return `text=${text}`;
      return null;
    };
    for (const el of document.querySelectorAll('a, button, input, select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=combobox], [onclick], [id*="btn_"], [id*="cbo_"], [id*="grd_"]')) {
      if (controls.length >= limit) break;
      if (!W.visible(el)) continue;
      const own = el.id ? el.id.split(':')[0] : '';
      if (own && seen.has(own)) continue;
      if (own) seen.add(own);
      const label = W.text(el).slice(0, 80) || el.getAttribute('aria-label') || el.getAttribute('title') || el.value || el.getAttribute('placeholder') || '';
      controls.push({kind: el.getAttribute('role') || el.type || el.tagName.toLowerCase(), label: String(label).slice(0, 80),
                     selector: selectorFor(el), id: own.length > 100 ? '…' + own.slice(-100) : own || undefined});
    }
    const tables = [...document.querySelectorAll('table, [role=grid]')].filter(W.visible).slice(0, 12).map((t, i) => {
      const rows = t.querySelectorAll('tr, [role=row]');
      const head = rows[0] ? [...rows[0].children].map(W.text).slice(0, 20) : [];
      return {index: i, rows: rows.length, first_row: head, id: t.id || undefined};
    }).filter(t => t.rows > 1);
    const tech = {nexacro: typeof nexacro !== 'undefined' && !!nexacro && typeof nexacro.getApplication === 'function',
                  microstrategy_session: !!W.mstr.globals(), content_frame: !!document.querySelector('iframe#content-frame'),
                  superset: !!document.querySelector('#app[data-bootstrap]') || location.pathname.startsWith('/superset')};
    if (tech.nexacro) {
      try { tech.nexacro_report_forms = W.nexacro.activeForms(); tech.nexacro_busy = W.nexacro.busy(); } catch (e) { /* not ready */ }
    }
    const loading = !!document.querySelector('#loading-spinner-container, .loading-spinner-container, .loading-overlay') &&
      [...document.querySelectorAll('#loading-spinner-container, .loading-spinner-container, .loading-overlay')].some(W.visible);
    return {title: document.title, url: location.pathname + location.search.slice(0, 200), technology: tech, loading,
            controls, tables, text: (document.body ? document.body.innerText : '').replace(/\n{2,}/g, '\n').slice(0, 3000),
            captured_requests: W.requests().length};
  };

  // Data requests this page made (kept in the page by Wizard). Each: {index, method, url, status, contentType, size,
  // body (first 500 characters), at}. W.request(i) is the full one; W.replay(i, change) sends it again.
  const store = () => (typeof window !== 'undefined' && window.__wizardRequests) || [];
  W.requests = (pattern = null) => store().map((r, index) => ({index, method: r.method, url: r.url.slice(0, 4000), status: r.status,
    contentType: r.contentType, size: r.size, body: r.body ? String(r.body).slice(0, 200000) : null, at: r.at, via: r.via}))
    .filter(r => !pattern || (pattern instanceof RegExp ? pattern.test(r.url) : r.url.includes(pattern)));
  W.request = index => {
    const all = store();
    const item = typeof index === 'number' ? all[index] : [...all].reverse().find(r => (index instanceof RegExp ? index.test(r.url) : r.url.includes(index)));
    if (!item) throw new Error(`no captured request ${String(index)}; W.requests() lists them`);
    return item;
  };
  // Send a captured request again, changing its body or URL: change = {body} | {replace: [[from, to], ...]} | {url}.
  // Uses the page's own session; Wizard still refuses anything that would write.
  W.replay = async (index, change = {}) => {
    const item = W.request(index);
    let body = change.body !== undefined ? change.body : item.body;
    let url = change.url || item.url;
    for (const [from, to] of change.replace || []) {
      body = typeof body === 'string' ? body.split(from).join(to) : body;
    }
    const headers = {...item.headers, ...(change.headers || {})};
    for (const name of Object.keys(headers)) if (/^(content-length|cookie|host)$/i.test(name)) delete headers[name];
    const response = await fetch(url, {method: item.method, headers, body: item.method === 'GET' ? undefined : body, credentials: 'include'});
    const text = await response.text();
    return {status: response.status, contentType: (response.headers.get('content-type') || '').split(';')[0], text};
  };
  // A response body in any format the portals use, as {datasets: {name: {columns, rows}}, parameters}.
  W.parse = text => {
    const t = String(text || '');
    if (t.startsWith('SSV')) return W.parseSSV(t);
    const s = t.trimStart();
    if (s.startsWith('<')) return W.parseXML(t);
    if (s.startsWith('{') || s.startsWith('[')) return {json: JSON.parse(t)};
    return {text: t.slice(0, 5000)};
  };
  // Nexacro SSV: records end with \x1e, units with \x1f, \x03 is null. Datasets start "Dataset:name", then a
  // "_RowType_" column record, then rows whose first unit is the row type.
  W.parseSSV = text => {
    const RS = '\x1e', US = '\x1f', NULL = '\x03';
    const records = String(text).split(RS);
    const out = {parameters: {}, datasets: {}};
    let current = null;
    for (let i = 1; i < records.length; i++) {
      const record = records[i].replace(/^\r?\n/, '');
      if (record === '' || record === '\r\n') { current = null; continue; }
      if (record.startsWith('Dataset:')) { current = {columns: [], rows: []}; out.datasets[record.slice(8).trim()] = current; continue; }
      if (current && record.startsWith('_RowType_')) { current.columns = record.split(US).slice(1).map(c => c.split(':')[0]); continue; }
      if (current && record.startsWith('_Const_')) continue;
      if (current && current.columns.length) {
        const units = record.split(US);
        if (units[0] === 'D') continue;
        current.rows.push(current.columns.map((_, c) => (units[c + 1] === NULL || units[c + 1] === undefined ? null : W.number(units[c + 1]))));
        continue;
      }
      for (const unit of record.split(US)) {
        const at = unit.indexOf('=');
        if (at > 0) out.parameters[unit.slice(0, at).split(':')[0]] = unit.slice(at + 1);
      }
    }
    return out;
  };
  // Nexacro (and generic) XML datasets: <Parameter id=…>, <Dataset id=…><ColumnInfo><Column id=…/>…<Rows><Row><Col id=…>.
  W.parseXML = text => {
    const doc = new DOMParser().parseFromString(String(text), 'application/xml');
    const out = {parameters: {}, datasets: {}};
    for (const p of doc.getElementsByTagName('Parameter')) out.parameters[p.getAttribute('id')] = p.textContent;
    for (const ds of doc.getElementsByTagName('Dataset')) {
      const columns = [...ds.getElementsByTagName('Column')].map(c => c.getAttribute('id'));
      const rows = [...ds.getElementsByTagName('Row')].filter(r => r.getAttribute('type') !== 'delete').map(r => {
        const values = {};
        for (const col of r.getElementsByTagName('Col')) values[col.getAttribute('id')] = col.textContent;
        return columns.map(c => (c in values ? W.number(values[c]) : null));
      });
      out.datasets[ds.getAttribute('id')] = {columns, rows};
    }
    return out;
  };

  // ---- GSCM: TOBESOFT Nexacro (from Metronome's GSCM adapter) ------------------------------------------------------
  // DOM ids are component paths (mainframe.VFrameSet.WorkFrame0.form.grd_list); a ":text"/":icontext" suffix is the
  // rendered caption of the component before it. Report windows are WorkFrame<N>; mainframe.waitwindow is the busy
  // overlay. Data lives in Datasets: read them instead of the screen.
  W.nexacro = {
    app: () => {
      if (typeof nexacro === 'undefined' || !nexacro || typeof nexacro.getApplication !== 'function') {
        throw new Error('nexacro is not in this frame; try the page itself or another frame');
      }
      return nexacro.getApplication();
    },
    resolve: path => {
      const pick = (col, key) => {
        if (!col) return null;
        try { if (col[key] != null) return col[key]; } catch (e) { /* no such key */ }
        try { if (Array.isArray(col)) { const named = col.find(x => x && (x.name === key || x.id === key)); if (named) return named; } } catch (e) { /* none */ }
        try { if (typeof col.get_item === 'function') { const v = col.get_item(key); if (v != null) return v; } } catch (e) { /* none */ }
        return null;
      };
      const parts = String(path || '').split(':', 1)[0].split('.')
        .filter(part => part && part !== '__proto__' && part !== 'prototype' && part !== 'constructor');
      const walk = (start, steps) => {
        let c = start;
        for (const part of steps) {
          let next = null;
          try { if (c && c[part] != null) next = c[part]; } catch (e) { /* not a property */ }
          if (!next && c) for (const k of ['components', 'frames', 'tabpages', 'all']) { try { next = pick(c[k], part); } catch (e) { /* none */ } if (next) break; }
          if (!next) return null;
          c = next;
        }
        return c;
      };
      const found = walk(W.nexacro.app(), parts);
      if (found || !parts.length) return found;
      // A pop-up (a Configuration dialog) is not under the application: its path starts with the pop-up's own name.
      for (const frame of W.nexacro.popupFrames()) {
        if (String(frame.name || frame.id || '') === parts[0]) { const inside = walk(frame, parts.slice(1)); if (inside) return inside; }
      }
      return null;
    },
    busy: () => {
      const o = document.getElementById('mainframe.waitwindow');
      if (!o) return false;
      const s = getComputedStyle(o);
      return s.display !== 'none' && s.visibility !== 'hidden' && o.getClientRects().length > 0;
    },
    // Waits until the overlay has been hidden for six checks in a row (Metronome's rule), at most ms.
    idle: async (ms = 120000) => {
      let quiet = 0;
      await W.waitFor(() => { quiet = W.nexacro.busy() ? 0 : quiet + 1; return quiet >= 6; }, ms, 500);
      return true;
    },
    // The visible report forms (WorkFrame<N>.form paths); usually exactly one is the active report.
    activeForms: () => {
      const wf = /(?:^|\.)work_?frame\d*(?:\.|$)/i;
      const bad = /(?:^|\.)(?:topframe|mdiframe|leftframe|bottomframe|setting\d*|waitwindow)(?:\.|$)/i;
      const out = new Set();
      for (const el of document.querySelectorAll('[id]')) {
        const id = String(el.id).split(':', 1)[0];
        if (!wf.test(id) || bad.test(id) || !W.visible(el)) continue;
        const m = id.match(/^(.*?work_?frame\d*)\.form(?:\.|$)/i);
        if (m) out.add(m[1] + '.form');
      }
      return [...out];
    },
    // The report title shown in a form (Metronome reads the sta_/lbl_/txt_ ...title component).
    title: formPath => {
      const form = String(formPath || W.nexacro.activeForms()[0] || '');
      const ids = [...document.querySelectorAll('[id]')].map(e => String(e.id).split(':', 1)[0])
        .filter(id => id.startsWith(form) && /(sta|lbl|txt)_?(user)?(bookmark|report)?_?(name|title)$/i.test(id));
      for (const id of ids) {
        const c = W.nexacro.resolve(id);
        try { const v = c && (typeof c.get_text === 'function' ? c.get_text() : c.text); if (v) return String(v); } catch (e) { /* next */ }
      }
      return null;
    },
    dataset: (owner, name) => {
      let ds = null;
      try { ds = owner[name] || (owner.datasets && (owner.datasets[name] || (typeof owner.datasets.get_item === 'function' && owner.datasets.get_item(name)))) || (owner.form && owner.form[name]); } catch (e) { /* none */ }
      return ds || null;
    },
    // The Dataset a Grid shows (getBindDataset, _binddataset, binddataset name looked up through the parents).
    boundDataset: grid => {
      if (typeof grid === 'string') grid = W.nexacro.resolve(grid);
      if (!grid) return null;
      let ds = null, name = null;
      try { if (typeof grid.getBindDataset === 'function') ds = grid.getBindDataset(); } catch (e) { /* older build */ }
      try { if (!ds && grid._binddataset) ds = grid._binddataset; } catch (e) { /* none */ }
      try { if (!ds && grid.binddataset) name = grid.binddataset; } catch (e) { /* none */ }
      try { if (!name && !ds && typeof grid.get_binddataset === 'function') name = grid.get_binddataset(); } catch (e) { /* none */ }
      if (typeof ds === 'string') { name = ds; ds = null; }
      if (!ds && name) {
        name = String(name).replace(/^@/, '');
        let o = grid;
        for (let d = 0; o && d < 12 && !ds; d++) { ds = W.nexacro.dataset(o, name); try { o = o.parent; } catch (e) { o = null; } }
        try { ds = ds || W.nexacro.app()[name]; } catch (e) { /* none */ }
      }
      return ds;
    },
    columns: ds => {
      const cols = [];
      try {
        if (typeof ds.getColCount === 'function' && typeof ds.getColID === 'function') {
          for (let i = 0; i < ds.getColCount(); i++) cols.push(ds.getColID(i));
        }
      } catch (e) { /* fall back below */ }
      if (!cols.length) {
        try { for (const info of (ds.colinfos || [])) cols.push(info.id || info.name); } catch (e) { /* none */ }
      }
      return cols.filter(Boolean);
    },
    // A Dataset as a table. limit caps the rows read (all by default); columns defaults to every column.
    read: (ds, {columns = null, limit = Infinity, unfiltered = false} = {}) => {
      if (typeof ds === 'string') ds = W.nexacro.resolve(ds) || W.nexacro.app()[ds];
      if (!ds || typeof ds.getRowCount !== 'function') throw new Error('not a Dataset');
      const cols = columns || W.nexacro.columns(ds);
      const nf = unfiltered && typeof ds.getRowCountNF === 'function' && typeof ds.getColumnNF === 'function';
      const total = nf ? ds.getRowCountNF() : ds.getRowCount();
      const rows = [];
      for (let r = 0; r < Math.min(total, limit); r++) {
        rows.push(cols.map(c => { const v = nf ? ds.getColumnNF(r, c) : ds.getColumn(r, c); return v === undefined ? null : W.plain(v); }));
      }
      return {columns: cols, rows, total_rows: total, dataset: String(ds.name || ds.id || '')};
    },
    // Every Dataset bound to a component inside a form (grids, combos), with its size and the component's path:
    // where a report's data is. W.nexacro.read(W.nexacro.boundDataset(entry.path)) reads one.
    datasets: formPath => {
      const app = W.nexacro.app();
      const root = formPath ? W.nexacro.resolve(formPath) : app.mainframe;
      if (!root) throw new Error(`no component at ${formPath}`);
      const out = [], seen = new Set();
      const visit = (c, path, d) => {
        if (!c || typeof c !== 'object' || d > 16 || seen.has(c)) return;
        seen.add(c);
        let ds = null;
        try { if (typeof c.getBindDataset === 'function' || c.binddataset) ds = W.nexacro.boundDataset(c); } catch (e) { /* none */ }
        if (ds && typeof ds.getRowCount === 'function') {
          out.push({path, component: String(c.name || c.id || ''), dataset: String(ds.name || ds.id || ''), rows: ds.getRowCount(),
                    columns: W.nexacro.columns(ds)});
        }
        for (const k of ['components', 'frames']) {
          let children; try { children = c[k]; } catch (e) { continue; }
          if (!children || typeof children.length !== 'number') continue;
          for (let i = 0; i < children.length && i < 5000; i++) {
            try { const child = children[i]; visit(child, `${path}.${child.name || child.id || i}`, d + 1); } catch (e) { /* skip */ }
          }
        }
        try { if (c.form) visit(c.form, `${path}.form`, d + 1); } catch (e) { /* none */ }
      };
      visit(root, formPath || 'mainframe', 0);
      return out;
    },
    // The rows a Grid shows: W.nexacro.readGrid('mainframe.VFrameSet.WorkFrame0.form.grd_list').
    readGrid: (grid, options = {}) => {
      const ds = W.nexacro.boundDataset(grid);
      if (!ds) throw new Error(`no Dataset is bound to ${typeof grid === 'string' ? grid : 'that grid'}`);
      return W.nexacro.read(ds, options);
    },
    // The person's GSCM bookmarks (Setting > Favorite), from the application dataset gds_bookmark. A scope tab's rows
    // load only after the tab was opened once in the Favorite dialog.
    bookmarks: () => {
      const ds = W.nexacro.app().gds_bookmark;
      if (!ds) return null;
      const columns = ['userreportid', 'userreportname', 'publicscope', 'scope', 'gbm', 'menuscope', 'menuid', 'menuname', 'menugroupid', 'menugroupname'];
      return W.nexacro.read(ds, {columns, unfiltered: true});
    },
    // The menu tree as one table to return and cite: the application Dataset of menus, every row. GSCM keeps it in
    // gds_topMenu (seen on the work PC, 29 Oct 2026); otherwise the biggest application Dataset named like a menu.
    // other_menu_datasets names the rest (a left or favourite menu). menu(name) reads a named one.
    menu: (name = null) => {
      const app = W.nexacro.app();
      const menus = W.nexacro.appDatasets().filter(s => /menu/i.test(s.name));
      const chosen = name || (menus.find(s => /^gds_?top_?menu$/i.test(s.name)) || menus[0] || {}).name;
      const ds = chosen ? W.nexacro.lookup(app, chosen) : null;
      if (!ds) throw new Error(`no menu Dataset${name ? ` named ${name}` : ''}: W.nexacro.appDatasets() lists the application's Datasets`);
      return {...W.nexacro.read(ds), dataset: chosen,
              other_menu_datasets: menus.filter(s => s.name !== chosen).map(s => `${s.name} (${s.rows} rows)`)};
    },
    // A Dataset by name as a component sees it: its own form, then each parent, then the application.
    lookup: (owner, name) => {
      name = String(name || '').replace(/^@/, '');
      let o = owner, ds = null;
      for (let d = 0; o && d < 12 && !ds; d++) { ds = W.nexacro.dataset(o, name); try { o = o.parent; } catch (e) { o = null; } }
      try { ds = ds || W.nexacro.app()[name]; } catch (e) { /* none */ }
      return ds && typeof ds.getRowCount === 'function' ? ds : null;
    },
    // The application's own Datasets (gds_*: the menu tree, codes, the user, bookmarks), biggest first: the menu
    // Dataset lists every report with its menu id, so the reports are found without clicking through menus.
    appDatasets: () => {
      const app = W.nexacro.app();
      const out = [], seen = new Set();
      const consider = (name, ds) => {
        if (!ds || typeof ds !== 'object' || typeof ds.getRowCount !== 'function' || seen.has(ds)) return;
        seen.add(ds);
        out.push({name: String(ds.name || ds.id || name), rows: ds.getRowCount(), columns: W.nexacro.columns(ds)});
      };
      for (const key of Object.keys(app)) { try { consider(key, app[key]); } catch (e) { /* a getter that throws */ } }
      try {
        const all = app.all;
        if (all && typeof all.length === 'number') for (let i = 0; i < all.length && i < 2000; i++) { try { const item = all[i]; consider(item && (item.name || item.id), item); } catch (e) { /* skip */ } }
      } catch (e) { /* no collection */ }
      return out.sort((a, b) => b.rows - a.rows);
    },
    // The pop-up windows open now (a report's Configuration dialog, a filter picker): Nexacro keeps them apart from
    // mainframe, so a walk from the application never meets them.
    popupFrames: () => {
      const out = [];
      try {
        const frames = typeof nexacro.getPopupFrames === 'function' ? nexacro.getPopupFrames() : null;
        const count = frames ? (typeof frames.length === 'number' ? frames.length : (frames.get_length ? frames.get_length() : 0)) : 0;
        for (let i = 0; i < count; i++) {
          const frame = frames[i] || (typeof frames.get_item === 'function' ? frames.get_item(i) : null);
          if (frame) out.push(frame);
        }
      } catch (e) { /* none open */ }
      return out;
    },
    // Every visible control whose caption, name or id matches `pattern` (text or RegExp), anywhere on screen: the report
    // and its toolbar (MdiFrame: a report's Configuration button may sit there, not in the report form), the top bar and
    // pop-ups. Read from the page's own ids (component paths; a caption is the element with the ":text" suffix), so
    // each match has a selector a click step can use.
    find: (pattern, {limit = 1000} = {}) => {
      const re = pattern instanceof RegExp ? pattern : new RegExp(String(pattern).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
      const found = new Map();
      for (const el of document.querySelectorAll('[id]')) {
        const id = String(el.id);
        const path = id.split(':', 1)[0];
        const label = document.getElementById(path + ':text') || document.getElementById(path + ':icontext');
        const caption = label ? (label.innerText || label.textContent || '').trim() : '';
        const name = path.split('.').pop() || '';
        if (!(caption && re.test(caption)) && !re.test(name)) continue;
        const owner = document.getElementById(path) || el;
        if (!W.visible(owner) || found.has(path)) continue;
        let type = '', enable = null;
        try { const c = W.nexacro.resolve(path); if (c) { type = String(c._type_name || ''); enable = c.enable === false ? false : true; } } catch (e) { /* not resolvable */ }
        found.set(path, {path, name, text: caption || null, type: type || null, ...(enable === false ? {enable} : {}),
                         where: /\.MdiFrame\./i.test(path) ? 'report toolbar' : /\.TopFrame\./i.test(path) ? 'top bar'
                           : /work_?frame/i.test(path) ? 'report' : 'pop-up or other', selector: `[id="${path}"]`});
        if (found.size >= limit) break;
      }
      return [...found.values()];
    },
    // Everything a configuration dialog offers, in one read: its controls (category and option buttons, tabs, radios,
    // checkboxes, with their state) and every list it shows (a Grid, ListBox or tree bound to a Dataset: its rows,
    // which columns are check marks, which rows are ticked). target: a path or component; default the newest pop-up,
    // else the active report. Read it after each category you open: a dialog often shows one category's list at a time.
    options: (target = null, {rows: maxRows = 20000} = {}) => {
      const popups = W.nexacro.popupFrames();
      let root = typeof target === 'string' ? W.nexacro.resolve(target) : target;
      let where = typeof target === 'string' ? target : target ? 'given component' : '';
      if (!root && popups.length) { root = popups[popups.length - 1]; where = `pop-up ${root.name || root.id || popups.length - 1}`; }
      if (!root) { where = W.nexacro.activeForms()[0] || ''; root = where ? W.nexacro.resolve(where) : null; }
      if (!root) throw new Error('no pop-up or report form is open');
      const get = (c, k) => { try { const g = c['get_' + k]; return typeof g === 'function' ? g.call(c) : c[k]; } catch (e) { return undefined; } };
      const controls = [], lists = [], seen = new Set(), sets = new Set();
      const flag = v => v === null || v === undefined || v === '' || [0, 1, true, false, '0', '1', 'Y', 'N', 'y', 'n', 'true', 'false'].includes(v);
      const ticked = v => [1, true, '1', 'Y', 'y', 'true'].includes(v);
      const visit = (c, path, d) => {
        if (!c || typeof c !== 'object' || d > 20 || seen.has(c) || controls.length >= 5000) return;
        seen.add(c);
        const type = String(c._type_name || '');
        if (/Button|Tab|Radio|CheckBox|Static|Menu/i.test(type) && !/Frame|Form$/i.test(type)) {
          const text = get(c, 'text');
          if (text != null && String(text).trim()) {
            const item = {path, type, text: String(text).slice(0, 120)};
            const value = get(c, 'value');
            if (value != null && value !== '') item.value = W.plain(value);
            if (get(c, 'visible') === false) item.visible = false;
            if (get(c, 'enable') === false) item.enable = false;
            controls.push(item);
          }
        }
        let ds = null;
        try { ds = typeof c.getInnerDataset === 'function' ? c.getInnerDataset() : null; } catch (e) { /* none */ }
        try { if (!ds && (typeof c.getBindDataset === 'function' || c.binddataset)) ds = W.nexacro.boundDataset(c); } catch (e) { /* none */ }
        if (ds && typeof ds.getRowCount === 'function' && !sets.has(ds)) {
          sets.add(ds);
          const table = W.nexacro.read(ds, {limit: maxRows});
          const checks = table.columns.filter((_, i) => table.rows.length && table.rows.every(r => flag(r[i]))
                                                     && table.rows.some(r => r[i] !== null && r[i] !== ''));
          const at = checks.map(name => table.columns.indexOf(name));
          lists.push({path, type, dataset: table.dataset, columns: table.columns, rows: table.rows, total_rows: table.total_rows,
                      check_columns: checks,
                      ticked_rows: at.length ? table.rows.map((r, i) => (at.some(j => ticked(r[j])) ? i : -1)).filter(i => i >= 0) : []});
        }
        for (const k of ['components', 'frames', 'tabpages']) {
          let children; try { children = c[k]; } catch (e) { continue; }
          if (!children || typeof children.length !== 'number') continue;
          for (let i = 0; i < children.length && i < 5000; i++) {
            try { const child = children[i]; visit(child, `${path}.${child.name || child.id || i}`, d + 1); } catch (e) { /* skip */ }
          }
        }
        try { if (c.form) visit(c.form, `${path}.form`, d + 1); } catch (e) { /* none */ }
      };
      visit(root, String(root.name || root.id || where || 'root'), 0);
      return {where, popups_open: popups.length, controls, lists};
    },
    // Every function of a form, its child forms (divs, tabs) and the open pop-ups: [where, name, fn]. own: the form's own
    // functions and its class's, not those every form inherits.
    _functionsOf: (root, where) => {
      const out = [], seen = new Set();
      const visit = (c, path, d) => {
        if (!c || typeof c !== 'object' || d > 10 || seen.has(c)) return;
        seen.add(c);
        const names = new Set();
        let o = c;
        for (let k = 0; o && k < 2 && o !== Object.prototype; k++) { try { Object.getOwnPropertyNames(o).forEach(n => names.add(n)); } catch (e) { /* none */ } o = Object.getPrototypeOf(o); }
        for (const name of names) {
          if (name === 'constructor' || name.startsWith('_')) continue;
          let fn; try { fn = c[name]; } catch (e) { continue; }
          if (typeof fn === 'function') out.push([path, name, fn]);
        }
        for (const k of ['components', 'tabpages']) {
          let children; try { children = c[k]; } catch (e) { continue; }
          if (!children || typeof children.length !== 'number') continue;
          for (let i = 0; i < children.length && i < 5000; i++) {
            try { const child = children[i]; if (child && child.form) visit(child.form, `${path}.${child.name || child.id || i}.form`, d + 1); } catch (e) { /* skip */ }
          }
        }
      };
      visit(root, where, 0);
      return out;
    },
    // A function's full code, to read what it sends or does: W.nexacro.source('fn_search') looks in the active report,
    // its child forms, the pop-ups, the top, left and toolbar forms and the application, in that order.
    source: (name, where = null) => {
      const places = where ? [[where, where === 'application' ? W.nexacro.app() : W.nexacro.resolve(where)]]
        : [...W.nexacro.activeForms().map(p => [p, W.nexacro.resolve(p)]),
           ...W.nexacro.popupFrames().map(f => [String(f.name || f.id || 'popup'), f.form || f]), ...W.nexacro.places()];
      for (const [path, owner] of places) {
        if (!owner) continue;
        for (const [at, fname, fn] of W.nexacro._functionsOf(owner, path)) {
          if (fname === name) { const text = String(fn); return {where: at, name, length: text.length, source: text}; }
        }
      }
      throw new Error(`no function ${name}${where ? ' at ' + where : ''}: W.nexacro.transactions() lists the report's functions`);
    },
    // Every data request a report's own code can send, read from its functions instead of watching the screen: each call
    // of transaction() (or a wrapper whose name says transaction, tran or service) with its arguments as written (service
    // id, address, input and output datasets, extra arguments, callback), every address ending in .do in its code, and
    // the application's wrappers, which say how an address is completed. Complete by construction: a request the screen
    // never sent is listed too. Read the arguments' datasets (W.nexacro.read) for the parameters each request carries.
    transactions: (formPath = null) => {
      const roots = formPath ? [[formPath, W.nexacro.resolve(formPath)]]
        : [...W.nexacro.activeForms().map(p => [p, W.nexacro.resolve(p)]),
           ...W.nexacro.popupFrames().map(f => [String(f.name || f.id || 'popup'), f.form || f])];
      if (!roots.some(([, r]) => r)) throw new Error('no report is open: open one first (W.nexacro.open)');
      const split = text => {  // a call's arguments, at the top level only (quotes, brackets and braces kept whole)
        const args = []; let depth = 0, quote = null, start = 0;
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (quote) { if (ch === '\\') { i++; continue; } if (ch === quote) quote = null; continue; }
          if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
          if ('([{'.includes(ch)) depth++;
          else if (')]}'.includes(ch)) { if (depth === 0) { args.push(text.slice(start, i).trim()); return {args, end: i}; } depth--; }
          else if (ch === ',' && depth === 0) { args.push(text.slice(start, i).trim()); start = i + 1; }
        }
        return {args, end: text.length};
      };
      const unquote = a => (/^(["'`])[\s\S]*\1$/.test(a || '') ? a.slice(1, -1) : a);
      const calls = [], addresses = new Set(), functions = [];
      const caller = /\b((?:this|application|nexacro\.getApplication\(\))\s*\.\s*)?([A-Za-z_$][\w$]*(?:transaction|Transaction|tran|Tran|service|Service)[\w$]*|transaction)\s*\(/g;
      for (const [root, owner] of roots) {
        if (!owner) continue;
        for (const [where, name, fn] of W.nexacro._functionsOf(owner, root)) {
          const text = String(fn);
          const sends = /transaction|\.do\b/.test(text);
          functions.push({where, name, length: text.length, ...(sends ? {sends: true} : {})});
          for (const m of text.matchAll(/["'`]([^"'`\s]*\.do)(?:\?[^"'`]*)?["'`]/g)) addresses.add(m[1]);
          caller.lastIndex = 0;
          let m;
          while ((m = caller.exec(text)) && calls.length < 10000) {
            if (/^function$/.test(m[2])) continue;
            const {args} = split(text.slice(m.index + m[0].length));
            // A call that sends: transaction() itself, or a wrapper given an address (a .do route, svc::name, a path).
            if (args.length < 2 || (!/transaction/i.test(m[2]) && !/\.do\b|::|\//.test(args[1]))) continue;
            calls.push({where, function: name, calls: m[2], service: unquote(args[0]), address: unquote(args[1]),
                        input: unquote(args[2] || ''), output: unquote(args[3] || ''), arguments: unquote(args[4] || ''),
                        callback: unquote(args[5] || ''), raw: (m[0] + args.join(', ') + ')').slice(0, 20000)});
          }
        }
      }
      const wrappers = [];
      try {
        for (const [where, name, fn] of W.nexacro._functionsOf(W.nexacro.app(), 'application')) {
          if (/tran|service/i.test(name)) wrappers.push({where, name, source: String(fn).replace(/\s+/g, ' ').slice(0, 20000)});
        }
      } catch (e) { /* no application */ }
      return {calls, addresses: [...addresses], wrappers,
              functions: functions.filter(f => f.sends).concat(functions.filter(f => !f.sends))};
    },
    // Where the client keeps its own functions: the application, the top, left and toolbar forms, the report forms.
    places: () => {
      const places = [['application', W.nexacro.app()]];
      for (const path of ['mainframe.VFrameSet.TopFrame.form', 'mainframe.VFrameSet.LeftFrame.form', 'mainframe.VFrameSet.MdiFrame.form', ...W.nexacro.activeForms()]) {
        const form = W.nexacro.resolve(path);
        if (form) places.push([path, form]);
      }
      return places;
    },
    // Calls one of the client's own functions with its owner as `this`, as the client does. Taken out of its form a
    // function fails (a run of 3 Nov 2026: "this.gfn_isNull is not a function"). name: 'fn_openMenu' (the first place
    // that has it, in W.nexacro.functions() order) or 'mainframe.VFrameSet.TopFrame.form.fn_openMenu' (that place).
    call: (name, ...args) => {
      const text = String(name || '');
      const cut = text.lastIndexOf('.');
      const fname = cut < 0 ? text : text.slice(cut + 1);
      const where = cut < 0 ? null : text.slice(0, cut);
      const owners = where === null ? W.nexacro.places()
        : [[where, where === 'application' ? W.nexacro.app() : W.nexacro.resolve(where)]];
      for (const [, owner] of owners) {
        let fn = null;
        try { fn = owner && owner[fname]; } catch (e) { /* none */ }
        if (typeof fn === 'function') return fn.apply(owner, args);
      }
      throw new Error(`no client function ${text}${where ? '' : ' on the application or its forms'}: W.nexacro.functions() lists them`);
    },
    // Waits until the client has finished starting: the application with its mainframe, the client's own functions
    // loaded, and no busy overlay. Calls made while it starts fail in different ways ("Cannot read properties of
    // undefined (reading 'mainframe')", a function missing on its form): call this after any page load.
    ready: async (ms = 90000) => {
      await W.waitFor(() => {
        const app = W.nexacro.app();
        return app && app.mainframe && W.nexacro.functions(undefined, 1).length > 0 && !W.nexacro.busy();
      }, ms, 500);
      await W.nexacro.idle(Math.min(ms, 30000)).catch(() => null);
      return true;
    },
    // Opens a report the way the client's menu does, in one step: waits for the client, calls its open function (the
    // map's topic names it, e.g. W.nexacro.open('fn_openMenu', 'DB4009')) with its owner as `this`, waits for the
    // report's window and the overlay, and says which form and title it found.
    open: async (name, ...args) => {
      const options = args.length > 1 && args[args.length - 1] && typeof args[args.length - 1] === 'object' ? args.pop() : {};
      const ms = options.ms || 120000;
      await W.nexacro.ready(ms);
      const before = new Set(W.nexacro.activeForms());
      const titleBefore = W.nexacro.title();
      const value = await W.nexacro.call(name, ...args);
      let form = null;
      await W.waitFor(() => {
        form = W.nexacro.activeForms().find(f => !before.has(f)) || null;
        return form || (W.nexacro.title() && W.nexacro.title() !== titleBefore);
      }, Math.min(ms, 60000), 500).catch(() => null);
      await W.nexacro.idle(ms).catch(() => null);
      form = form || W.nexacro.activeForms()[0] || null;
      return {called: String(name), args, returned: value === undefined ? null : value, form,
              title: form ? W.nexacro.title(form) : null, new_window: !!form && !before.has(form)};
    },
    // The client's own functions (gfn_/fn_ by Nexacro convention): shortcuts such as opening a report by menu id. On
    // the application, the top, left and toolbar forms and the active report, with the start of each source to read
    // its parameters. pattern: a RegExp or text to choose other names.
    functions: (pattern = /^(g|l|c)?fn_|^gfn|^fn[A-Z]/, limit = 5000) => {
      const re = pattern instanceof RegExp ? pattern : new RegExp(String(pattern), 'i');
      const out = [];
      for (const [where, owner] of W.nexacro.places()) {
        const names = new Set();
        let o = owner;
        for (let d = 0; o && d < 2 && o !== Object.prototype; d++) { try { Object.getOwnPropertyNames(o).forEach(n => names.add(n)); } catch (e) { /* none */ } o = Object.getPrototypeOf(o); }
        for (const name of names) {
          if (!re.test(name)) continue;
          let fn; try { fn = owner[name]; } catch (e) { continue; }
          if (typeof fn !== 'function') continue;
          out.push({where, name, source: String(fn).replace(/\s+/g, ' ').slice(0, 240)});
          if (out.length >= limit) return out;
        }
      }
      return out;
    },
    // A report form's inputs (filters, buttons, grids): type, name, caption, value, and a combo's options from its
    // inner Dataset as "code = label" (the first `options`, with the count). What a question needs to set filters.
    inputs: (formPath = null, {options = 5000} = {}) => {
      const start = formPath || W.nexacro.activeForms()[0];
      const root = start ? W.nexacro.resolve(start) : null;
      if (!root) throw new Error(`no form at ${start || 'the active report'}; open a report first`);
      const out = [], seen = new Set();
      const kinds = /Combo|Calendar|Edit|TextArea|Radio|CheckBox|ListBox|Spin|Button|Grid|DateField|ListView/i;
      const get = (c, k) => { try { const g = c['get_' + k]; return typeof g === 'function' ? g.call(c) : c[k]; } catch (e) { return undefined; } };
      const visit = (c, path, d) => {
        if (!c || typeof c !== 'object' || d > 20 || seen.has(c) || out.length >= 5000) return;
        seen.add(c);
        const type = String(c._type_name || (c.constructor && c.constructor.name) || '');
        if (kinds.test(type) && !/Frame|Form$/i.test(type)) {
          const item = {path, type, name: String(c.name || c.id || '')};
          const text = get(c, 'text');
          if (text != null && text !== '') item.text = String(text).slice(0, 120);
          const value = get(c, 'value');
          if (value != null && value !== '') item.value = W.plain(value);
          if (get(c, 'visible') === false) item.visible = false;
          if (get(c, 'enable') === false) item.enable = false;
          let inner = null;
          try { inner = typeof c.getInnerDataset === 'function' ? c.getInnerDataset() : null; } catch (e) { /* none */ }
          if (!inner) { const name = get(c, 'innerdataset'); if (name) inner = typeof name === 'string' ? W.nexacro.lookup(c.parent || root, name) : name; }
          if (inner && typeof inner.getRowCount === 'function') {
            const code = get(c, 'codecolumn'), label = get(c, 'datacolumn');
            item.options_dataset = String(inner.name || inner.id || '');
            item.options_count = inner.getRowCount();
            const columns = [code, label].filter(Boolean);
            if (columns.length) item.options = W.nexacro.read(inner, {columns, limit: options}).rows.map(r => r.join(' = '));
          }
          if (/Grid/i.test(type)) {
            const ds = W.nexacro.boundDataset(c);
            if (ds) { item.dataset = String(ds.name || ds.id || ''); item.rows = ds.getRowCount(); item.columns = W.nexacro.columns(ds); }
          }
          out.push(item);
        }
        for (const k of ['components', 'frames']) {
          let children; try { children = c[k]; } catch (e) { continue; }
          if (!children || typeof children.length !== 'number') continue;
          for (let i = 0; i < children.length && i < 5000; i++) {
            try { const child = children[i]; visit(child, `${path}.${child.name || child.id || i}`, d + 1); } catch (e) { /* skip */ }
          }
        }
        try { if (c.form) visit(c.form, `${path}.form`, d + 1); } catch (e) { /* none */ }
      };
      visit(root, start, 0);
      return out;
    },
  };

  // ---- ASAP: a portal shell with MicroStrategy Web in iframe#content-frame (from Metronome's ASAP adapter) -----------
  W.mstr = {
    globals: () => {
      try {
        // eslint-disable-next-line no-undef
        const common = typeof _COMMON_INFO !== 'undefined' ? _COMMON_INFO : window._COMMON_INFO;
        // eslint-disable-next-line no-undef
        const session = typeof _SESSION !== 'undefined' ? _SESSION : window._SESSION;
        return common && session ? {common, session} : null;
      } catch (e) { return null; }
    },
    fromHtml: html => {
      const grab = name => {
        const m = new RegExp(`(?:const|var|let)\\s+${name}\\s*=\\s*\\{`).exec(html);
        if (!m) return null;
        let depth = 0, i = m.index + m[0].length - 1, inString = null;
        for (let j = i; j < html.length; j++) {
          const ch = html[j];
          if (inString) { if (ch === '\\') j++; else if (ch === inString) inString = null; continue; }
          if (ch === '"' || ch === "'") inString = ch;
          else if (ch === '{') depth++;
          else if (ch === '}' && --depth === 0) { try { return JSON.parse(html.slice(i, j + 1)); } catch (e) { return null; } }
        }
        return null;
      };
      const common = grab('_COMMON_INFO'), session = grab('_SESSION');
      return common && session ? {common, session} : null;
    },
    raw: () => {
      let found = W.mstr.globals();
      const docs = [document];
      for (const f of document.querySelectorAll('iframe, frame')) { try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) { /* other origin */ } }
      for (const d of docs) { if (found) break; try { found = W.mstr.fromHtml(d.documentElement.outerHTML); } catch (e) { /* none */ } }
      return found;
    },
    // Where MicroStrategy Web lives and the person's role menu. The session token stays inside these helpers.
    // Read it on the signed-in landing page: report pages may not carry it.
    session: () => {
      const found = W.mstr.raw();
      if (!found) return null;
      const path = String(found.common.MSTR_CUSTOM_WEB_CONTEXT_PATH || '/mstr').replace(/\/$/, '');
      return {web_base: location.origin + path, main_menu_id: found.common.MSTR_MAIN_MENU_ID || null,
              signed_in: !!found.session.MSTRWEB_AUTH_TOKEN_ENC};
    },
    // One menu folder from {web_base}/menuInfo.do (POST, authToken + depth), unwrapped: {id, name, children}.
    menu: async (folderId = null, depth = 1) => {
      const found = W.mstr.raw();
      if (!found || !found.session.MSTRWEB_AUTH_TOKEN_ENC) throw new Error('no ASAP session on this page; open the ASAP start page first');
      const path = String(found.common.MSTR_CUSTOM_WEB_CONTEXT_PATH || '/mstr').replace(/\/$/, '');
      const id = folderId || found.common.MSTR_MAIN_MENU_ID;
      const response = await fetch(`${location.origin}${path}/menuInfo.do?folderId=${encodeURIComponent(id)}`, {
        method: 'POST', credentials: 'include',
        headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({authToken: found.session.MSTRWEB_AUTH_TOKEN_ENC, depth: String(depth)}).toString()});
      if (!response.ok) throw new Error(`menuInfo.do answered ${response.status}`);
      let value = await response.json();
      if (value && typeof value === 'object' && 'data' in value) {
        const code = value.errorCode;
        if (!(code == null || code === 0 || code === '0' || String(code).toLowerCase() === 'success')) throw new Error(`menuInfo.do error ${code}`);
        value = value.data;
        if (typeof value === 'string') value = JSON.parse(value);
        if (Array.isArray(value)) value = {id, children: value};
      }
      return value;
    },
    // The whole report menu as paths: [{path: [top, group, report], id}], walked the way Metronome does.
    reports: async () => {
      const clean = name => String(name || '').replace(/^\d+\./, '').replace(/\s+/g, ' ').trim();
      const kids = node => (node && (node.children || node.child)) || [];
      const out = [];
      const walk = (node, parents) => {
        const name = clean(node.name);
        const path = name ? [...parents, name] : parents;
        const children = kids(node);
        if (children.length) for (const child of children) walk(child, path);
        else if (node.id && path.length >= 2) out.push({path, id: String(node.id)});
      };
      let root = await W.mstr.menu(null, 1);
      if (!kids(root).length) root = await W.mstr.menu(null, 2);
      for (const top of kids(root)) {
        const subtree = top.id ? await W.mstr.menu(top.id, 2) : top;
        const prefix = subtree && clean(subtree.name) !== clean(top.name) ? [clean(top.name)] : [];
        walk(subtree && kids(subtree).length ? subtree : top, prefix);
      }
      return out;
    },
    // MicroStrategy's own document: the newest live iframe#content-frame (it is replaced on every report open and RUN).
    contentWindow: () => {
      const frames = [...document.querySelectorAll('iframe#content-frame')].reverse();
      for (const f of frames) { try { if (f.contentWindow && f.contentDocument) return f.contentWindow; } catch (e) { /* replaced */ } }
      return null;
    },
    loading: (doc = document) => [...doc.querySelectorAll('#loading-spinner-container, .loading-spinner-container, .loading-overlay')].some(W.visible),
    // A report has rendered when "Data rows:" shows, or (raw-data views) a table of 2+ rows with a download hint.
    rendered: (doc = document) => {
      const text = doc.body ? doc.body.innerText : '';
      if (/Data rows:/.test(text)) return true;
      return /to download raw data/i.test(text) && [...doc.querySelectorAll('table')].some(t => t.querySelectorAll('tr').length >= 2);
    },
  };

  // ---- BDP: Apache Superset under the person's own sign-in ----------------------------------------------------------
  W.superset = {
    csrf: async () => (await W.fetchJson('/api/v1/security/csrf_token/')).json?.result || null,
    databases: async () => {
      const r = await W.fetchJson('/api/v1/database/?q=' + encodeURIComponent('(page_size:100)'));
      return (r.json?.result || []).map(d => ({id: d.id, name: d.database_name, backend: d.backend, allow_dml: d.allow_dml}));
    },
    schemas: async databaseId => (await W.fetchJson(`/api/v1/database/${databaseId}/schemas/`)).json?.result || [],
    // One SELECT through SQL Lab (Wizard refuses anything else): {columns, rows, total_rows}.
    sql: async (databaseId, sql, {schema = null, limit = 1000} = {}) => {
      const token = await W.superset.csrf();
      const response = await fetch('/api/v1/sqllab/execute/', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/json', Accept: 'application/json', ...(token ? {'X-CSRFToken': token} : {})},
        body: JSON.stringify({database_id: databaseId, sql, schema, runAsync: false, queryLimit: limit, client_id: Math.random().toString(36).slice(2, 12)})});
      const body = await response.json().catch(() => null);
      if (!response.ok || !body) throw new Error(`SQL Lab answered ${response.status}: ${JSON.stringify(body).slice(0, 400)}`);
      if (body.status && body.status !== 'success') throw new Error(`SQL Lab: ${body.status} ${body.error || ''}`.trim());
      const columns = (body.columns || []).map(c => c.column_name || c.name);
      return {columns, rows: (body.data || []).map(row => columns.map(c => row[c] ?? null)), total_rows: (body.data || []).length};
    },
  };
  return W;
})();
