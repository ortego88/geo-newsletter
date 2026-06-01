/**
 * push.js — Registro de push notifications via Capacitor + FCM
 * Solo se activa cuando la web corre dentro de la app nativa (Capacitor).
 */
(function () {
  // Solo ejecutar si estamos dentro de Capacitor (app nativa)
  if (!window.Capacitor || !window.Capacitor.isNativePlatform()) return;

  async function registerPush() {
    try {
      const { PushNotifications } = window.Capacitor.Plugins;
      if (!PushNotifications) return;

      // Pedir permiso
      const perm = await PushNotifications.requestPermissions();
      if (perm.receive !== 'granted') return;

      // Registrar en FCM
      await PushNotifications.register();

      // Cuando Firebase devuelve el token, enviarlo al backend
      PushNotifications.addListener('registration', async function (data) {
        try {
          await fetch('/api/fcm-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ token: data.value }),
          });
        } catch (e) {
          console.warn('FCM token registration failed:', e);
        }
      });

      // Notificación recibida con la app abierta — mostrar badge en el nav si hay una
      PushNotifications.addListener('pushNotificationReceived', function (notification) {
        console.log('Push received:', notification.title);
      });

      // Usuario toca la notificación — navegar si viene con datos
      PushNotifications.addListener('pushNotificationActionPerformed', function (action) {
        const data = action.notification.data || {};
        if (data.type === 'alert' && data.asset) {
          // Navegar al historial filtrando por el activo
          window.location.href = '/historial?asset=' + encodeURIComponent(data.asset);
        } else if (data.type === 'result' && data.prediction_id) {
          window.location.href = '/historial';
        }
      });

    } catch (e) {
      console.warn('Push setup error:', e);
    }
  }

  // Esperar a que Capacitor esté listo
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', registerPush);
  } else {
    registerPush();
  }
})();
