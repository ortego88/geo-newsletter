/**
 * nav.js - Funciones globales para la navegación
 * Se carga en todas las páginas que usan partials/nav.html
 */

// Menú móvil hamburguesa
function toggleMobileNav() {
  var menu = document.getElementById('mobile-nav-menu');
  if (menu) {
    menu.classList.toggle('hidden');
  }
}

function closeMobileNav() {
  var menu = document.getElementById('mobile-nav-menu');
  if (menu) {
    menu.classList.add('hidden');
  }
}

// Dropdown de usuario
function toggleUserMenu() {
  var dropdown = document.getElementById('user-dropdown');
  if (dropdown) {
    dropdown.classList.toggle('hidden');
  }
}

// Cerrar menús al hacer clic fuera
document.addEventListener('DOMContentLoaded', function() {
  document.addEventListener('click', function(event) {
    // Cerrar menú móvil
    var menu = document.getElementById('mobile-nav-menu');
    var btn = document.getElementById('mobile-nav-btn');

    if (menu && btn && !menu.classList.contains('hidden')) {
      if (!btn.contains(event.target) && !menu.contains(event.target)) {
        menu.classList.add('hidden');
      }
    }

    // Cerrar dropdown de usuario
    var userDropdown = document.getElementById('user-dropdown');
    var userBtn = document.getElementById('user-menu-btn');

    if (userDropdown && userBtn && !userDropdown.classList.contains('hidden')) {
      if (!userBtn.contains(event.target) && !userDropdown.contains(event.target)) {
        userDropdown.classList.add('hidden');
      }
    }
  });
});
