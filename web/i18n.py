"""
web/i18n.py — Diccionario de traducciones server-side.
Se inyecta en todos los templates via context_processor.
Uso en templates: {{ t.alerts }} {{ t.next }} {{ t.history_title }}
"""

ES = {
    # Navbar
    "nav_pricing": "Precios",
    "nav_faq": "FAQ",
    "nav_login": "Iniciar sesión",
    "nav_start_free": "Empezar gratis",
    "nav_history": "Historial",
    "nav_blog": "Blog",
    "nav_sign_out": "Cerrar sesión",
    "nav_dashboard": "Dashboard",
    "nav_settings": "Configuración",
    "nav_subscription": "Suscripción",
    "nav_private_area": "Área personal",

    # Common
    "next": "Siguiente →",
    "previous": "← Anterior",
    "save": "Guardar",
    "cancel": "Cancelar",
    "loading": "Cargando...",

    # History / Dashboard
    "history_title": "Historial de Alertas",
    "alerts": "Alertas",
    "accuracy": "% Aciertos",
    "correct": "Correctas",
    "incorrect": "Incorrectas",
    "pending": "Pendientes",
    "neutral": "Neutrales",
    "high_confidence": "Conf. alta (≥70%)",
    "correct_incorrect": "Correctas / Incorrectas",
    "all_history": "Todo el historial",
    "last_24h": "Últimas 24 horas",
    "last_7d": "Últimos 7 días",
    "last_30d": "Últimos 30 días",
    "all_assets": "Todos los activos",
    "crypto": "Criptomonedas",
    "ibex35": "IBEX 35",
    "etf": "ETFs",
    "filter_outcome": "Resultado",
    "all_outcomes": "Todos",
    "no_predictions": "No hay predicciones en el histórico.",
    "register_cta": "¿Quieres recibir estas alertas en tu Telegram?",
    "free_trial": "7 días gratis, sin compromiso",
    "start_free": "Empezar gratis →",

    # Table columns
    "col_title": "Título",
    "col_asset": "Activo",
    "col_direction": "Dir",
    "col_confidence": "Conf.",
    "col_score": "Score",
    "col_price_entry": "Precio entrada",
    "col_price_valid": "Precio valid.",
    "col_change": "Cambio real",
    "col_outcome": "Resultado",
    "col_date": "Fecha",

    # Outcome badges
    "outcome_correct": "Correcto",
    "outcome_incorrect": "Incorrecto",
    "outcome_pending": "Pendiente",
    "outcome_neutral": "Neutral",

    # Settings
    "settings_title": "Configuración",
    "assets_title": "Activos a monitorizar",
    "assets_desc": "Selecciona los activos para los que deseas recibir alertas de Telegram.",
    "search_placeholder": "Buscar activo por nombre o símbolo...",
    "maximum": "Máximo",
    "unlimited": "Ilimitado",
    "select_all": "Seleccionar todos",
    "deselect_all": "Quitar todos",
    "upgrade_msg": "¿Necesitas más activos?",
    "upgrade_plan": "Actualizar plan →",
    "lang_title": "Idioma de las alertas",
    "telegram_title": "Telegram Chat ID",
    "telegram_desc": "Para recibir alertas en Telegram, necesitas tu Chat ID personal. Habla con @userinfobot en Telegram y te lo enviará.",
    "save_settings": "Guardar configuración",
    "changes_locked": "Cambios bloqueados temporalmente",
    "changes_locked_desc": "Guardaste tu última configuración hace menos de 24 horas.",
    "asset_changes": "Cambios en activos",
    "asset_changes_desc": "Puedes seleccionar y cambiar libremente antes de guardar. Una vez guardes, deberás esperar 24 horas antes de poder modificar tu selección nuevamente.",

    # Subscription
    "subscription_title": "Suscripción",
    "current_plan": "Plan actual",
    "trial_badge": "Prueba gratuita",
    "active_badge": "Activo",
    "cancel_pending_badge": "Cancelación pendiente",
    "trial_until": "Prueba gratuita hasta el",
    "next_charge": "Próximo cobro el",
    "access_until": "Tu acceso finalizará el",
    "assets_label": "Activos",
    "alerts_day": "Alertas/día",
    "history_days": "Historial",
    "activate_sub": "Activar suscripción",
    "activate_with_card": "Activar suscripción con tarjeta guardada",
    "cancel_sub": "Cancelar suscripción",
    "view_plans": "Ver todos los planes",
    "no_active_plan": "Sin plan activo",
    "reactivate": "Reactivar suscripción",

    # Trial/Activation messages
    "trial_active": "Período de prueba activo",
    "trial_ends": "Tu prueba gratuita finaliza el",
    "add_payment": "Añade tu método de pago para no perder el acceso.",
    "activate_plan": "Activar plan",

    # Dashboard
    "dashboard_title": "Dashboard",
}

EN = {
    # Navbar
    "nav_pricing": "Pricing",
    "nav_faq": "FAQ",
    "nav_login": "Sign in",
    "nav_start_free": "Start free",
    "nav_history": "History",
    "nav_blog": "Blog",
    "nav_sign_out": "Sign out",
    "nav_dashboard": "Dashboard",
    "nav_settings": "Settings",
    "nav_subscription": "Subscription",
    "nav_private_area": "Private area",

    # Common
    "next": "Next →",
    "previous": "← Previous",
    "save": "Save",
    "cancel": "Cancel",
    "loading": "Loading...",

    # History / Dashboard
    "history_title": "Alert History",
    "alerts": "Alerts",
    "accuracy": "% Accuracy",
    "correct": "Correct",
    "incorrect": "Incorrect",
    "pending": "Pending",
    "neutral": "Neutral",
    "high_confidence": "High conf. (≥70%)",
    "correct_incorrect": "Correct / Incorrect",
    "all_history": "All history",
    "last_24h": "Last 24 hours",
    "last_7d": "Last 7 days",
    "last_30d": "Last 30 days",
    "all_assets": "All assets",
    "crypto": "Cryptocurrencies",
    "ibex35": "IBEX 35",
    "etf": "ETFs",
    "filter_outcome": "Outcome",
    "all_outcomes": "All",
    "no_predictions": "No predictions in history.",
    "register_cta": "Want to receive these alerts on Telegram?",
    "free_trial": "7 days free, no commitment",
    "start_free": "Start free →",

    # Table columns
    "col_title": "Title",
    "col_asset": "Asset",
    "col_direction": "Dir",
    "col_confidence": "Conf.",
    "col_score": "Score",
    "col_price_entry": "Entry price",
    "col_price_valid": "Valid. price",
    "col_change": "Real change",
    "col_outcome": "Outcome",
    "col_date": "Date",

    # Outcome badges
    "outcome_correct": "Correct",
    "outcome_incorrect": "Incorrect",
    "outcome_pending": "Pending",
    "outcome_neutral": "Neutral",

    # Settings
    "settings_title": "Settings",
    "assets_title": "Assets to monitor",
    "assets_desc": "Select the assets you want to receive Telegram alerts for.",
    "search_placeholder": "Search asset by name or symbol...",
    "maximum": "Maximum",
    "unlimited": "Unlimited",
    "select_all": "Select all",
    "deselect_all": "Deselect all",
    "upgrade_msg": "Need more assets?",
    "upgrade_plan": "Upgrade plan →",
    "lang_title": "Alert language",
    "telegram_title": "Telegram Chat ID",
    "telegram_desc": "To receive Telegram alerts, you need your personal Chat ID. Talk to @userinfobot on Telegram and it will send it to you.",
    "save_settings": "Save settings",
    "changes_locked": "Changes temporarily locked",
    "changes_locked_desc": "You saved your last settings less than 24 hours ago.",
    "asset_changes": "Asset changes",
    "asset_changes_desc": "You can freely select and change before saving. Once saved, you must wait 24 hours before modifying again.",

    # Subscription
    "subscription_title": "Subscription",
    "current_plan": "Current plan",
    "trial_badge": "Free trial",
    "active_badge": "Active",
    "cancel_pending_badge": "Cancellation pending",
    "trial_until": "Free trial until",
    "next_charge": "Next charge on",
    "access_until": "Your access will end on",
    "assets_label": "Assets",
    "alerts_day": "Alerts/day",
    "history_days": "History",
    "activate_sub": "Activate subscription",
    "activate_with_card": "Activate subscription with saved card",
    "cancel_sub": "Cancel subscription",
    "view_plans": "View all plans",
    "no_active_plan": "No active plan",
    "reactivate": "Reactivate subscription",

    # Trial/Activation messages
    "trial_active": "Active trial period",
    "trial_ends": "Your free trial ends on",
    "add_payment": "Add your payment method to keep access.",
    "activate_plan": "Activate plan",

    # Dashboard
    "dashboard_title": "Dashboard",
}

TRANSLATIONS = {"es": ES, "en": EN}


def get_translations(lang: str) -> dict:
    """Devuelve el diccionario de traducciones para el idioma dado."""
    return TRANSLATIONS.get(lang, ES)
