// Landing-page bilingual toggle (DE primary, EN secondary).
// No build step — vanilla JS. Active language is stored on <html data-lang>
// and persisted in localStorage; CSS hides the inactive [lang] elements.
(function () {
  'use strict';

  var KEY = 'autosplat-lang';
  var SUPPORTED = ['de', 'en'];
  var root = document.documentElement;

  function pickInitial() {
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode */ }
    if (SUPPORTED.indexOf(saved) !== -1) return saved;
    // Fall back to the browser preference, defaulting to German.
    var nav = (navigator.language || 'de').slice(0, 2).toLowerCase();
    return nav === 'en' ? 'en' : 'de';
  }

  function apply(lang) {
    if (SUPPORTED.indexOf(lang) === -1) lang = 'de';
    root.setAttribute('data-lang', lang);
    root.setAttribute('lang', lang);
    var buttons = document.querySelectorAll('[data-set-lang]');
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      b.setAttribute('aria-pressed', String(b.getAttribute('data-set-lang') === lang));
    }
    try { localStorage.setItem(KEY, lang); } catch (e) { /* ignore */ }
  }

  // Apply as early as possible to avoid a flash of the wrong language.
  apply(pickInitial());

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-set-lang]');
    if (!btn) return;
    apply(btn.getAttribute('data-set-lang'));
  });
})();
