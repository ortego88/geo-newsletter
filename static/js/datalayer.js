(function() {
  'use strict';

  var debugPanel = null;
  var STORAGE_KEY = 'dl_debug_log';
  var DEBUG_FLAG_KEY = 'dl_debug_enabled';

  // Expose global toggle: type debug=true or debug=false in console
  Object.defineProperty(window, 'debug', {
    set: function(val) {
      if (val) {
        localStorage.setItem(DEBUG_FLAG_KEY, '1');
        window.__DL_DEBUG = true;
        initDebugPanel();
        if (debugPanel) debugPanel.style.display = '';
      } else {
        localStorage.removeItem(DEBUG_FLAG_KEY);
        window.__DL_DEBUG = false;
        if (debugPanel) debugPanel.style.display = 'none';
      }
    },
    get: function() { return !!window.__DL_DEBUG; }
  });

  // Restore from localStorage
  if (localStorage.getItem(DEBUG_FLAG_KEY) === '1') {
    window.__DL_DEBUG = true;
  }

  function getStoredLogs() {
    try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || []; }
    catch(e) { return []; }
  }

  function storeLogs(logs) {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(logs)); }
    catch(e) {}
  }

  function clearLogs() {
    sessionStorage.removeItem(STORAGE_KEY);
    var list = document.getElementById('dl-debug-list');
    if (list) list.innerHTML = '';
  }

  function initDebugPanel() {
    if (debugPanel || !window.__DL_DEBUG) return;
    debugPanel = document.createElement('div');
    debugPanel.id = 'dl-debug';
    debugPanel.style.cssText = 'position:fixed;bottom:0;left:0;right:0;max-height:40vh;overflow-y:auto;background:#0f172a;border-top:2px solid #E8B84B;font-family:monospace;font-size:11px;z-index:99999;padding:8px 12px;color:#e2e8f0;';
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;position:sticky;top:0;background:#0f172a;padding:4px 0;z-index:1;';
    header.innerHTML = '<span style="color:#E8B84B;font-weight:bold;">dataLayer Debug</span><div><button id="dl-debug-clear" style="color:#f87171;background:none;border:1px solid #f87171;border-radius:4px;cursor:pointer;font-size:10px;padding:2px 8px;margin-right:8px;">Borrar</button><button id="dl-debug-close" style="color:#94a3b8;background:none;border:none;cursor:pointer;font-size:16px;">✕</button></div>';
    debugPanel.appendChild(header);
    var list = document.createElement('div');
    list.id = 'dl-debug-list';
    debugPanel.appendChild(list);
    document.body.appendChild(debugPanel);
    document.getElementById('dl-debug-close').onclick = function() {
      debugPanel.style.display = debugPanel.style.display === 'none' ? '' : 'none';
    };
    document.getElementById('dl-debug-clear').onclick = clearLogs;

    // Render stored logs
    var stored = getStoredLogs();
    for (var i = 0; i < stored.length; i++) {
      renderEntry(stored[i].type, stored[i].data, stored[i].time, stored[i].page);
    }
  }

  function renderEntry(type, data, time, page) {
    var list = document.getElementById('dl-debug-list');
    if (!list) return;
    var color = type === 'pageview' ? '#34d399' : '#60a5fa';
    var entry = document.createElement('div');
    entry.style.cssText = 'border-bottom:1px solid #1e293b;padding:6px 0;';
    var lines = '<div style="margin-bottom:2px;"><span style="color:#64748b;">' + time + '</span> <span style="color:' + color + ';font-weight:bold;">[' + type + ']</span>';
    if (page) lines += ' <span style="color:#475569;font-size:10px;">' + page + '</span>';
    lines += '</div>';
    for (var k in data) {
      if (data[k]) {
        lines += '<div style="padding-left:12px;"><span style="color:#94a3b8;">' + k + ':</span> <span style="color:#e2e8f0;">' + data[k] + '</span></div>';
      }
    }
    entry.innerHTML = lines;
    list.insertBefore(entry, list.firstChild);
  }

  function logToPanel(type, data) {
    if (!window.__DL_DEBUG) return;
    initDebugPanel();
    var time = new Date().toLocaleTimeString();
    var page = location.pathname;
    renderEntry(type, data, time, page);
    // Persist
    var logs = getStoredLogs();
    logs.unshift({type: type, data: data, time: time, page: page});
    if (logs.length > 200) logs = logs.slice(0, 200);
    storeLogs(logs);
  }

  function getPageContext() {
    var dl = window.dataLayer || [];
    var ctx = {};
    for (var i = dl.length - 1; i >= 0; i--) {
      if (dl[i] && dl[i].eventName === 'pageview') {
        ctx.pageName = dl[i].pageName || '';
        ctx.sectionName = dl[i].sectionName || '';
        ctx.serviceType = dl[i].serviceType || '';
        ctx.userStatus = dl[i].userStatus || '';
        ctx.userType = dl[i].userType || '';
        ctx.userPlan = dl[i].userPlan || '';
        ctx.language = dl[i].language || '';
        break;
      }
    }
    return ctx;
  }

  function pushInteraction(el) {
    window.dataLayer = window.dataLayer || [];
    // Always use 'interaction' as GTM event name to avoid collision with native 'click' trigger
    var dlEventName = el.getAttribute('data-dl-event') || 'interaction';
    var ctx = getPageContext();
    var payload = {
      'event': dlEventName,          // GTM trigger listens for this exact string
      'eventName': dlEventName,
      // Interaction-specific params — must be top-level for GTM dataLayer variables
      'action': el.getAttribute('data-dl-action') || '',
      'format': el.getAttribute('data-dl-format') || '',
      'component': el.getAttribute('data-dl-component') || '',
      'element': el.getAttribute('data-dl-element') || '',
      'interactionType': el.getAttribute('data-dl-action') || 'click',
      // Page context (carried from pageview push)
      'pageName': ctx.pageName,
      'sectionName': ctx.sectionName,
      'serviceType': ctx.serviceType || 'crypto_alerts',
      'userStatus': ctx.userStatus,
      'userType': ctx.userType,
      'userPlan': ctx.userPlan,
      'language': ctx.language || document.documentElement.lang || 'es',
      'pathname': window.location.pathname
    };
    window.dataLayer.push(payload);
    logToPanel(dlEventName, payload);
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
