(function() {
  'use strict';

  function pushInteraction(el) {
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({
      'event': el.getAttribute('data-dl-event') || 'click',
      'eventName': el.getAttribute('data-dl-event') || 'click',
      'action': el.getAttribute('data-dl-action') || 'click',
      'format': el.getAttribute('data-dl-format') || '',
      'component': el.getAttribute('data-dl-component') || '',
      'element': el.getAttribute('data-dl-element') || ''
    });
  }

  document.addEventListener('click', function(e) {
    var el = e.target.closest('[data-dl-action]');
    if (!el) return;
    var action = el.getAttribute('data-dl-action');
    if (action === 'submit') return;
    pushInteraction(el);
  });

  document.addEventListener('submit', function(e) {
    var form = e.target.closest('[data-dl-action]');
    if (!form) return;
    pushInteraction(form);
  });

  document.addEventListener('change', function(e) {
    var el = e.target.closest('[data-dl-action]');
    if (!el) return;
    var action = el.getAttribute('data-dl-action');
    if (action === 'select' || action === 'check' || action === 'uncheck') {
      var element = el.getAttribute('data-dl-element') || '';
      if (element === '{value}') {
        el.setAttribute('data-dl-element', e.target.value || e.target.textContent);
      }
      pushInteraction(el);
    }
  });
})();
