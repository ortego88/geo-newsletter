from datetime import datetime, timedelta, UTC
from dateutil import parser


def filter_recent(articles, minutes=60):

    now = datetime.now(UTC)
    limit = now - timedelta(minutes=minutes)

    recent = []

    for a in articles:

        t = (
            a.get("publishedAt")
            or a.get("pubDate")
            or a.get("published")
            or a.get("date")
            or a.get("created")
        )

        if not t:
            continue

        try:

            published = parser.parse(str(t))

            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)

        except:
            continue

        if published > limit:
            recent.append(a)

    return recent