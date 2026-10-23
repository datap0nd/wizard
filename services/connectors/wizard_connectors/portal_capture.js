// Wizard: keeps the last data requests this page made (XMLHttpRequest and fetch), in the page only, so a Gemini script
// can call one again with its own parameters (W.requests, W.replay) without the request body or session token ever
// leaving the browser. Added to every frame of Wizard's background browser; never to the person's sign-in window.
(() => {
  if (window.__wizardRequests) return;
  const kept = [];
  const LIMIT = 60, BODY = 200000, TEXT = 2000000;
  Object.defineProperty(window, '__wizardRequests', {value: kept, enumerable: false});
  const keep = item => { kept.push(item); if (kept.length > LIMIT) kept.shift(); };
  const asText = body => {
    if (body == null) return null;
    if (typeof body === 'string') return body.slice(0, BODY);
    if (body instanceof URLSearchParams) return body.toString().slice(0, BODY);
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      try { return new URLSearchParams([...body.entries()].filter(([, v]) => typeof v === 'string')).toString(); } catch (e) { return '<form>'; }
    }
    return '<binary>';
  };
  const XHR = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
  if (XHR) {
    const open = XHR.open, send = XHR.send, header = XHR.setRequestHeader;
    XHR.open = function (method, url) {
      try { this.__wizard = {method: String(method || 'GET').toUpperCase(), url: new URL(url, location.href).href, headers: {}, at: Date.now(), via: 'xhr'}; } catch (e) {}
      return open.apply(this, arguments);
    };
    XHR.setRequestHeader = function (name, value) {
      try { if (this.__wizard) this.__wizard.headers[name] = value; } catch (e) {}
      return header.apply(this, arguments);
    };
    XHR.send = function (body) {
      const item = this.__wizard;
      if (item) {
        item.body = asText(body);
        this.addEventListener('loadend', () => {
          try {
            item.status = this.status;
            item.contentType = (this.getResponseHeader('content-type') || '').split(';')[0];
            const text = (this.responseType === '' || this.responseType === 'text') ? this.responseText : null;
            item.response = text == null ? null : text.slice(0, TEXT);
            item.size = text == null ? null : text.length;
            keep(item);
          } catch (e) {}
        });
      }
      return send.apply(this, arguments);
    };
  }
  if (window.fetch) {
    const original = window.fetch;
    window.fetch = function (input, init) {
      let item = null;
      try {
        const request = input instanceof Request ? input : null;
        const headers = {};
        new Headers((init && init.headers) || (request && request.headers) || {}).forEach((v, k) => { headers[k] = v; });
        item = {method: String((init && init.method) || (request && request.method) || 'GET').toUpperCase(),
                url: new URL(request ? request.url : String(input), location.href).href, headers,
                body: asText(init && init.body), at: Date.now(), via: 'fetch'};
      } catch (e) {}
      const pending = original.apply(this, arguments);
      if (item && !(init && init.__wizardSkip)) {
        pending.then(response => {
          item.status = response.status;
          item.contentType = (response.headers.get('content-type') || '').split(';')[0];
          response.clone().text().then(text => { item.response = text.slice(0, TEXT); item.size = text.length; keep(item); },
                                       () => keep(item));
        }, () => {});
      }
      return pending;
    };
  }
})();
