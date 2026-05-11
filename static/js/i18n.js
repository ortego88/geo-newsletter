/**
 * i18n.js - Sistema de idioma global
 * Se carga en todas las páginas del dashboard
 */

var GEO_LANG = localStorage.getItem('geo_lang') || 'es';

function setLanguage(lang) {
  localStorage.setItem('geo_lang', lang);
  GEO_LANG = lang;

  // Intentar guardar en servidor (falla silenciosamente si no está autenticado)
  fetch('/dashboard/set-language', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language: lang })
  }).finally(function() {
    window.location.reload();
  });
}

// Aplicar traducciones al cargar
document.addEventListener('DOMContentLoaded', function() {
  // Buscar el diccionario de traducciones disponible
  var dict = (typeof TRANSLATIONS !== 'undefined') ? TRANSLATIONS
           : (typeof DASH_TRANSLATIONS !== 'undefined') ? DASH_TRANSLATIONS
           : null;

  if (dict) {
    var t = dict[GEO_LANG] || dict['es'];
    document.querySelectorAll('[data-i18n]').forEach(function(el) {
      var key = el.getAttribute('data-i18n');
      if (t[key]) el.textContent = t[key];
    });
  }

  // Actualizar el indicador de idioma en el nav si existe
  var langCode = document.getElementById('lang-code');
  if (langCode) langCode.textContent = GEO_LANG.toUpperCase();
});
