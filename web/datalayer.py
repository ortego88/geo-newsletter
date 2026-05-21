"""
DataLayer configuration for GTM pageview tracking.
Maps Flask route endpoints to their dataLayer variable values.
"""

PAGE_DATALAYER_CONFIG = {
    "main.landing": {
        "pageName": "home",
        "sectionName": "home",
        "serviceType": "home",
        "webArea": "public",
    },
    "main.app_home": {
        "pageName": "appHome",
        "sectionName": "app",
        "serviceType": "home",
        "webArea": "public",
    },
    "billing.pricing": {
        "pageName": "pricing",
        "sectionName": "pricing",
        "serviceType": "productInformation",
        "webArea": "public",
    },
    "main.history": {
        "pageName": "history",
        "sectionName": "history",
        "serviceType": "productInformation",
        "webArea": "public",
    },
    "blog.index": {
        "pageName": "blog",
        "sectionName": "blog",
        "serviceType": "news",
        "webArea": "public",
    },
    "blog.post": {
        "pageName": "blog",
        "sectionName": "blog",
        "serviceType": "news",
        "webArea": "public",
    },
    "main.privacy": {
        "pageName": "privacy",
        "sectionName": "privacy",
        "serviceType": "serviceInformation",
        "webArea": "public",
    },
    "main.terms": {
        "pageName": "terms",
        "sectionName": "terms",
        "serviceType": "serviceInformation",
        "webArea": "public",
    },
    "auth.login": {
        "pageName": "login",
        "sectionName": "login",
        "processType": "login",
        "serviceType": "userLogin",
        "webArea": "public",
    },
    "auth.register": {
        "pageName": "register/step01/personalDetails",
        "sectionName": "register",
        "processType": "register",
        "processStep": "step01",
        "processDetail": "personalDetails",
        "serviceType": "userRegister",
        "webArea": "public",
    },
    "billing.checkout_trial": {
        "pageName": "register/step02/paymentDetails",
        "sectionName": "register",
        "processType": "register",
        "processStep": "step02",
        "processDetail": "paymentDetails",
        "serviceType": "userRegister",
        "webArea": "public",
    },
    "billing.success": {
        "pageName": "register/success",
        "sectionName": "register",
        "processType": "register",
        "processStep": "success",
        "serviceType": "userRegister",
        "webArea": "public",
    },
    "dashboard_web.index": {
        "pageName": "dashboard",
        "sectionName": "dashboard",
        "serviceType": "productInformation",
        "webArea": "private",
    },
    "dashboard_web.my_assets": {
        "pageName": "assets",
        "sectionName": "assets",
        "serviceType": "productInformation",
        "webArea": "private",
    },
    "dashboard_web.settings": {
        "pageName": "settings",
        "sectionName": "settings",
        "serviceType": "userSettings",
        "webArea": "private",
    },
    "dashboard_web.subscription": {
        "pageName": "subscription",
        "sectionName": "subscription",
        "serviceType": "userSettings",
        "webArea": "private",
    },
}


def get_datalayer_pageview(endpoint, view_args=None, request_args=None):
    """Build the pageview dataLayer dict for the current request."""
    config = PAGE_DATALAYER_CONFIG.get(endpoint)
    if not config:
        return None

    dl = {
        "eventName": "pageview",
        "pageName": config.get("pageName", ""),
        "sectionName": config.get("sectionName", ""),
        "processType": config.get("processType", ""),
        "processStep": config.get("processStep", ""),
        "processDetail": config.get("processDetail", ""),
        "interactionType": "view",
        "serviceType": config.get("serviceType", ""),
        "productName": "",
        "webArea": config.get("webArea", "public"),
    }

    if endpoint == "blog.post" and view_args and "slug" in view_args:
        dl["pageName"] = f"blog/{view_args['slug']}"

    if endpoint == "dashboard_web.my_assets" and request_args:
        dl["productName"] = request_args.get("asset", "")

    return dl
