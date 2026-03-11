import json
from collectors.news.gdelt_collector import fetch_gdelt
from collectors.news.newsapi_collector import fetch_news
from collectors.news.rss_collector import fetch_rss
from collectors.news.google_news_collector import fetch_google_news
from collectors.news.energy_rss_collector import fetch_energy_news

from collectors.osint.osint_collector import fetch_osint
from collectors.osint.liveuamap_collector import fetch_liveuamap
from collectors.osint.crisis24_collector import fetch_crisis24
from collectors.osint.acled_collector import fetch_acled
from collectors.osint.firms_collector import fetch_firms
from collectors.osint.shipping_collector import fetch_shipping
# from collectors.osint.reddit_collector import fetch_reddit

from pipeline.market_filter import market_relevant
from pipeline.deduplicate import deduplicate
from pipeline.rank_events import rank_events
from pipeline.cluster_events import cluster_events
from pipeline.recent_filter import filter_recent
from pipeline.semantic_deduplicate import semantic_deduplicate

from analysis.impact_model import impact_score
from analysis.tension_index import compute_tension
from analysis.early_signal_detector import detect_early_signals
from analysis.event_correlation_engine import correlate_events
from analysis.event_graph import detect_event_clusters

from detection.asset_detection import detect_assets
from detection.geopolitical_classifier import classify_event
from detection.location_detection import detect_location
from detection.event_confidence import event_confidence
from detection.critical_event_detector import detect_critical_event
from detection.energy_infrastructure_detector import detect_energy_event
from detection.chokepoint_detector import detect_chokepoint

from nlp.summarizer import summarize

from datetime import datetime, UTC
from dateutil import parser

from outputs.newsletter_generator import generate_newsletter
from outputs.telegram_sender import send_telegram

from storage.memory import already_sent, store_alert
from storage.article_store import load_processed, save_processed, article_id

def get_trusted_sources(events):

    sources = []

    for e in events:

        src = e.get("source","")

        if not src:
            continue

        if src in TRUSTED_SOURCES and src not in sources:
            sources.append(src)

        if len(sources) == 3:
            break

    return sources

def market_impact_label(score):

    if score >= 75:
        return "Very High"

    if score >= 60:
        return "High"

    if score >= 45:
        return "Moderate"

    return "Low"

def run():

    processed = load_processed()

    # ---------------------
    # Collect sources
    # ---------------------

    osint_posts = []

    try:
        osint_posts = fetch_osint()
    except Exception as e:
        print("OSINT collector error:", e)

    articles = (
        fetch_gdelt()
        + fetch_news()
        + fetch_rss()
        + fetch_google_news()
        + fetch_energy_news()
        + fetch_liveuamap()
        + fetch_crisis24()
        + fetch_acled()
        + fetch_shipping()
        + fetch_firms()
        + osint_posts
    )

    if len(articles) == 0:
        return

    print("Collected:", len(articles))

    articles = filter_recent(articles, minutes=180)

    print("Last hour articles:", len(articles))

    articles = [a for a in articles if market_relevant(a)]

    print("After market filter:", len(articles))

    new_articles = []

    for a in articles:

        aid = article_id(a)

        if aid in processed:
            continue

        processed.add(aid)
        new_articles.append(a)

    recent_articles = articles
    articles = new_articles

    print("New articles:", len(articles))

    signals = detect_early_signals(articles)

    from experiment.signal_logger import log_signal

    for s in signals:

        if s["mentions"] < 3:
            continue

        example_text = " ".join(s.get("examples", []))

        location = "Unknown (Global)"

        loc_data = detect_location(example_text)

        if loc_data:
            location = f"{loc_data.get('location','Unknown')} ({loc_data.get('region','Global')})"

        log_signal(
            s["signal"],
            location,
            "osint"
        )

        message = (
            f"⚠️ Early OSINT signal detected\n\n"
            f"Signal: {s['signal']}\n"
            f"Location: {location}\n"
            f"Mentions: {s['mentions']}\n\n"
        )

        message += "Sources:\n"

        for src in list(s.get("sources", []))[:5]:
            message += f"- {src}\n"

        message += "\nArticles:\n"

        for u in list(s.get("urls", []))[:5]:
            message += f"- {u}\n"

        import hashlib

        signal_id = hashlib.md5(s["signal"].encode()).hexdigest()

        if not already_sent(signal_id):
            send_telegram(message)
            store_alert(signal_id)

    # ---------------------
    # Filter recent news
    # ---------------------

    if articles:
        print("Example article date:", articles[0].get("publishedAt"))

    # ---------------------
    # Remove noise
    # ---------------------

    articles = deduplicate(articles)
    articles = semantic_deduplicate(articles)

    if not articles:
        print("No new relevant news")
        return

    print("After relevance filter:", len(articles))

    # ---------------------
    # Compute tension index
    # ---------------------

    tension_index = compute_tension(articles)

    # ---------------------
    # Build events
    # ---------------------

    articles = [
        a for a in articles
        if len((a.get("title") or "")) > 30
    ]

    events = []

    for a in recent_articles:

        title = a.get("title") or ""
        desc = a.get("description") or a.get("summary") or ""
        content = a.get("content") or ""

        text = f"{title} {desc} {content}"

        loc_data = detect_location(text)
        location = f"{loc_data['location']} ({loc_data['region']})"

        critical_event = detect_critical_event(text)

        energy_event = detect_energy_event(text)
        chokepoint = detect_chokepoint(text)

        src = a.get("source", "unknown")

        if isinstance(src, list):
            sources = src

        elif isinstance(src, str):
            sources = [src]

        else:
            sources = ["unknown"]

        confidence = event_confidence(sources)

        score = impact_score(text, tension_index)

        event = {

            "title": title,
            "summary": summarize(text),
            "location": location,
            "region": loc_data["region"],
            "lat": loc_data["lat"],
            "lon": loc_data["lon"],
            "critical_event": critical_event,
            "category": classify_event(text),
            "assets": detect_assets(text),
            "energy_event": energy_event,
            "chokepoint": chokepoint,
            "impact_score": score,
            "confidence": confidence,
            "sources": sources,
            "url": a.get("url") or a.get("link") or "",
            "timestamp": datetime.now(UTC).isoformat()

        }

        events.append(event)

    try:
        with open("storage/events_history.json") as f:
            history = json.load(f)

            if not isinstance(history, list):
                history = []

    except:
        history = []

    history.extend(events)

    history = history[-5000:]

    with open("storage/events_history.json", "w") as f:
        json.dump(history, f)
    # ---------------------
    # Cluster similar events
    # ---------------------

    events = cluster_events(events)
    clusters = detect_event_clusters(events)

    print("\nCLUSTER RESULTS\n")

    for e in events[:10]:

        sources = e.get("sources",[])

        if len(sources) < 2 and e["impact_score"] < 70:
            continue

        if isinstance(sources,list):
            count = len(sources)
        else:
            count = 1

        print(
            count,
            "|",
            e["title"][:70]
        )

    import hashlib

    for c in clusters:

        cluster_id = hashlib.md5(c["cluster"].encode()).hexdigest()

        if already_sent(cluster_id):
            continue

        message = (
            f"⚠️ Escalating geopolitical risk\n\n"
            f"Cluster: {c['cluster']}\n"
            f"Events detected: {c['count']}\n\n"
        )

        for e in c["events"][:3]:
            message += f"- {e['title']}\n"

        send_telegram(message)

        store_alert(cluster_id)

    # ---------------------
    # Rank events
    # ---------------------

    ranked_events = rank_events(events)

    print("\nEVENT SOURCE COUNTS\n")

    for e in ranked_events[:10]:

        src = e.get("sources", [])

        if isinstance(src,list):
            count = len(src)
        else:
            count = 1

        print(
            count,
            "|",
            e["title"][:70]
        )

    # ---------------------
    # Select important alerts
    # ---------------------

    for e in ranked_events[:10]:
        print(e["impact_score"], e["title"])

    alerts = []

    for e in ranked_events:

        if e["impact_score"] < 40:
            continue

        sources = e.get("sources", [])

        if not isinstance(sources, list):
            sources = [sources]

        if len(sources) < 2:
            continue

        fingerprint = (
            e["title"][:60]
            + e["location"]
            + e["critical_event"]
        )

        alert_id = hashlib.md5(fingerprint.encode()).hexdigest()

        if already_sent(alert_id):
            continue

        alerts.append(e)
        store_alert(alert_id)

        if len(alerts) == 5:
            break

    if not alerts:
        print("No alerts to send")
        return

    # ---------------------
    # Generate message
    # ---------------------

    message = generate_newsletter(alerts)

    print(message)

    # ---------------------
    # Send Telegram alert
    # ---------------------

    send_telegram(message)

    save_processed(processed)

    try:

        with open("storage/alerts_history.json") as f:
            alerts_history = json.load(f)

    except:
        alerts_history = []

    alerts_history.extend(alerts)

    with open("storage/alerts_history.json","w") as f:
        json.dump(alerts_history,f)

if __name__ == "__main__":
    run()