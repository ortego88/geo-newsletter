var GTM_ID = 'GTM-P5XZX4DR';

function cookieConsent(level) {
  localStorage.setItem('geo_cookie_consent', level);
  var banner = document.getElementById('cookie-banner');
  if (banner) banner.style.display = 'none';
  if (level === 'all') loadGTM();
}

function initCookieBanner() {
  var consent = localStorage.getItem('geo_cookie_consent');
  if (!consent) {
    var banner = document.getElementById('cookie-banner');
    if (banner) banner.style.display = 'block';
  } else if (consent === 'all') {
    loadGTM();
  }
}

function loadGTM() {
  if (window._gtmLoaded) return;
  window._gtmLoaded = true;
  (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
  new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
  j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
  'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
  })(window,document,'script','dataLayer',GTM_ID);
}

window.cookieConsent = cookieConsent;
window.initCookieBanner = initCookieBanner;
window.loadGTM = loadGTM;

document.addEventListener('DOMContentLoaded', initCookieBanner);
