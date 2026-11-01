// In the access request window only: tells Wizard which control the person pressed (its text, and whether it sits in a
// form or dialog), so the request their Submit sends can be told from the page's other requests. It reads nothing else
// and changes nothing on the page.
(() => {
  if (window.__wizardClickWatch) return;
  window.__wizardClickWatch = true;
  document.addEventListener('click', event => {
    const el = event.target instanceof Element
      ? event.target.closest('button, input[type="submit"], input[type="button"], input[type="image"], [role="button"], a') : null;
    if (!el || el.closest('#wizard-access-banner') || typeof window.__wizardClicked !== 'function') return;
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    const inForm = !!el.closest('form, dialog, [role="dialog"], [aria-modal="true"], [class*="modal" i], [class*="drawer" i]');
    Promise.resolve(window.__wizardClicked({text, inForm})).catch(() => {});
  }, true);
})();
