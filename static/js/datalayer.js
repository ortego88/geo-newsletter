(function() {
  'use strict';

  var debugPanel = null;
  var debugLog = [];

  function initDebugPanel() {
    if (debugPanel || !window.__DL_DEBUG) return;
    debugPanel = document.createElement('div');
    debugPanel.id = 'dl-debug';
    debugPanel.style.cssText = 'position:fixed;bottom:0;left:0;right:0;max-height:35vh;overflow-y:auto;background:#0f172a;border-top:2px solid #E8B84B;font-family:monospace;font-size:11px;z-index:99999;padding:8px;color:#e2e8f0;';
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;position:sticky;top:0;background:#0f172a;padding:2px 0;';
    header.innerHTML = '<span style="color:#E8B84B;font-weight:bold;">dataLayer Debug</span><button id="dl-debug-close" style="color:#94a3b8;background:none;border:none;cursor:pointer;font-size:14px;">✕</button>';
    debugPanel.appendChild(header);
    var list = document.createElement('div');
    list.id = 'dl-debug-list';
    debugPanel.appendChild(list);
    document.body.appendChild(debugPanel);
    document.getElementById('dl-debug-close').onclick = function() {
      debugPanel.style.display = debugPanel.style.display === 'none' ? '' : 'none';
    };
  }

  function logToPanel(type, data) {
    if (!window.__DL_DEBUG) return;
    initDebugPanel();
    var list = document.getElementById('dl-debug-list');
    if (!list) return;
    var time = new Date().toLocaleTimeString();
    var color = type === 'pageview' ? '#34d399' : '#60a5fa';
    var entry = document.createElement('div');
    entry.style.cssText = 'border-bottom:1px solid #1e293b;padding:3px 0;';
    var parts = [];
    for (var k in data) {
      if (data[k]) parts.push('<span style="color:#94a3b8;">' + k + ':</span>' + data[k]);
    }
    entry.innerHTML = '<span style="color:#64748b;">' + time + '</span> <span style="color:' + color + ';font-weight:bold;">[' + type + ']</span> ' + parts.join(' · ');
    list.insertBefore(entry, list.firstChild);
  }

  function pushInteraction(el) {
    window.dataLayer = window.dataLayer || [];
    var payload = {
      'event': el.getAttribute('data-dl-event') || 'click',
      'eventName': el.getAttribute('data-dl-event') || 'click',
      'action': el.getAttribute('data-dl-action') || 'click',
      'format': el.getAttribute('data-dl-format') || '',
      'component': el.getAttribute('data-dl-component') || '',
      'element': el.getAttribute('data-dl-element') || ''
    };
    window.dataLayer.push(payload);
    logToPanel(payload.eventName, payload);
  }

  // Log the initial pageview push
  document.addEventListener('DOMContentLoaded', function() {
    if (!window.__DL_DEBUG) return;
    initDebugPanel();
    var dl = window.dataLayer || [];
    for (var i = 0; i < dl.length; i++) {
      if (dl[i] && dl[i].eventName === 'pageview') {
        logToPanel('pageview', dl[i]);
      }
    }
  });

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
