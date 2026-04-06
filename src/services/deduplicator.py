"""
Deduplicador de artículos.
Persiste hashes de artículos ya vistos en data/seen_articles.txt.
"""

import hashlib
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("deduplicator")

DEFAULT_SEEN_FILE = "data/seen_articles.txt"
MAX_AGE_DAYS = 7  # Purgar hashes más antiguos de N días


def _article_hash(article: dict) -> str:
    title = (article.get("title") or "").strip().lower()
    url = (article.get("url") or article.get("link") or "").strip()
    raw = f"{title}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()


class Deduplicator:
    def __init__(self, seen_file: str = DEFAULT_SEEN_FILE):
        self.seen_file = seen_file
        os.makedirs(os.path.dirname(seen_file), exist_ok=True)
        self._seen: set[str] = self._load()

    def _load(self) -> set[str]:
        if not os.path.exists(self.seen_file):
            return set()
        seen = set()
        try:
            with open(self.seen_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        # Formato: hash|timestamp (timestamp opcional)
                        parts = line.split("|")
                        seen.add(parts[0])
        except Exception as e:
            logger.warning(f"Error cargando artículos vistos: {e}")
        return seen

    def _save(self):
        try:
            with open(self.seen_file, "w", encoding="utf-8") as f:
                now_str = datetime.utcnow().isoformat()
                for h in self._seen:
                    f.write(f"{h}|{now_str}\n")
        except Exception as e:
            logger.warning(f"Error guardando artículos vistos: {e}")

    def is_seen(self, article: dict) -> bool:
        return _article_hash(article) in self._seen

    def mark_seen(self, article: dict):
        h = _article_hash(article)
        self._seen.add(h)

    def deduplicate(self, articles: list[dict]) -> list[dict]:
        """
        Filtra artículos ya vistos. Marca los nuevos como vistos y persiste.
        """
        new_articles = []
        for article in articles:
            if not self.is_seen(article):
                new_articles.append(article)
                self.mark_seen(article)

        if new_articles:
            self._save()

        logger.info(
            f"Deduplicación: {len(articles)} entradas → {len(new_articles)} nuevas"
        )
        return new_articles
