"""
Deduplicador de artículos — dos niveles:

  Nivel 1 (rápido):
    - Hash de URL exacta
    - Hash de título normalizado (lowercase, sin acentos, sin puntuación)

  Nivel 2 (semántico):
    - TF-IDF + cosine similarity contra noticias de las últimas 48h del mismo ticker
    - Umbral configurable DEDUP_SIMILARITY_THRESHOLD (0.75 por defecto)
    - Fallback a difflib.SequenceMatcher si scikit-learn no está disponible

Los hashes del Nivel 1 se persisten en data/seen_articles.txt.
Los textos recientes del Nivel 2 se guardan en data/recent_articles.db (SQLite).
"""

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta

logger = logging.getLogger("deduplicator")

DEFAULT_SEEN_FILE = "data/seen_articles.txt"
DEFAULT_RECENT_DB = "data/recent_articles.db"
MAX_AGE_DAYS = 7        # Purgar hashes del Nivel 1 más antiguos de N días
RECENT_HOURS = 48       # Ventana para deduplicación semántica (Nivel 2)

# Umbral de similitud coseno — fácilmente ajustable
DEDUP_SIMILARITY_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Utilidades de normalización de texto
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Normaliza texto para comparación: lowercase, sin acentos, sin puntuación."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_hash(title: str) -> str:
    """Hash MD5 del título normalizado para dedup rápida de Nivel 1."""
    return hashlib.md5(normalize_text(title).encode()).hexdigest()


def _article_url_hash(article: dict) -> str:
    """Hash MD5 de título+URL (dedup exacta de Nivel 1 original)."""
    title = (article.get("title") or "").strip().lower()
    url = (article.get("url") or article.get("link") or "").strip()
    raw = f"{title}|{url}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Deduplicación semántica — Nivel 2
# ---------------------------------------------------------------------------

def is_duplicate_news(
    new_title: str,
    new_description: str,
    existing_recent_news: list[tuple[str, str]],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> tuple[bool, float]:
    """
    Comprueba si una noticia nueva es duplicado semántico de alguna reciente
    del mismo ticker.

    Args:
        new_title: título de la noticia nueva
        new_description: descripción de la noticia nueva
        existing_recent_news: lista de (título, descripción) de noticias recientes
                              (últimas 48h, mismo ticker)
        threshold: umbral de similitud coseno (0.75 por defecto)

    Returns:
        (is_duplicate, max_similarity) — True si es duplicado, con la similitud máxima.
    """
    if not existing_recent_news:
        return False, 0.0

    new_text = normalize_text(f"{new_title} {new_description[:500]}")
    existing_texts = [
        normalize_text(f"{t} {d[:500]}") for t, d in existing_recent_news
    ]

    all_texts = [new_text] + existing_texts

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(min_df=1, analyzer="word", ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])
        max_similarity = float(similarities.max()) if similarities.size > 0 else 0.0
        return max_similarity > threshold, max_similarity

    except Exception:
        # Fallback: comparación simple con difflib
        from difflib import SequenceMatcher

        max_ratio = 0.0
        for existing_text in existing_texts:
            ratio = SequenceMatcher(None, new_text, existing_text).ratio()
            if ratio > max_ratio:
                max_ratio = ratio
        # difflib ratios are slightly different — use 0.80 as fallback threshold
        return max_ratio > 0.80, max_ratio


# ---------------------------------------------------------------------------
# Almacenamiento de artículos recientes para Nivel 2
# ---------------------------------------------------------------------------

class RecentArticleStore:
    """
    Persiste los artículos recientes en SQLite para poder comparar en ejecuciones
    posteriores (ventana de RECENT_HOURS horas, mismo ticker).
    """

    def __init__(self, db_path: str = DEFAULT_RECENT_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recent_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    title_hash TEXT NOT NULL,
                    stored_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticker_stored "
                "ON recent_articles(ticker, stored_at)"
            )
            conn.commit()

    def get_recent(self, ticker: str) -> list[tuple[str, str]]:
        """Devuelve (title, description) de artículos del ticker en las últimas RECENT_HOURS h."""
        cutoff = (datetime.utcnow() - timedelta(hours=RECENT_HOURS)).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT title, description FROM recent_articles "
                "WHERE ticker = ? AND stored_at >= ?",
                (ticker, cutoff),
            ).fetchall()
        return [(r[0], r[1] or "") for r in rows]

    def title_hash_exists(self, ticker: str, title_hash: str) -> bool:
        """Comprueba si ya existe un artículo con este hash de título para este ticker."""
        cutoff = (datetime.utcnow() - timedelta(hours=RECENT_HOURS)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM recent_articles "
                "WHERE ticker = ? AND title_hash = ? AND stored_at >= ?",
                (ticker, title_hash, cutoff),
            ).fetchone()
        return row is not None

    def add(self, ticker: str, title: str, description: str):
        """Guarda un artículo en la tienda de recientes."""
        th = _title_hash(title)
        stored_at = datetime.utcnow().isoformat()
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO recent_articles (ticker, title, description, title_hash, stored_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ticker, title, description or "", th, stored_at),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"[DEDUP] Error guardando artículo reciente: {e}")

    def purge_old(self):
        """Elimina artículos más antiguos que RECENT_HOURS horas."""
        cutoff = (datetime.utcnow() - timedelta(hours=RECENT_HOURS)).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM recent_articles WHERE stored_at < ?", (cutoff,)
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Deduplicador principal
# ---------------------------------------------------------------------------

class Deduplicator:
    """
    Deduplicador de dos niveles:

    - Nivel 1a: hash de URL+título (idéntico exacto) — persiste en seen_articles.txt
    - Nivel 1b: hash de título normalizado — persiste en seen_articles.txt
    - Nivel 2: similitud semántica TF-IDF contra artículos de las últimas 48h
               (requiere que el artículo tenga 'ticker' asignado)
    """

    def __init__(
        self,
        seen_file: str = DEFAULT_SEEN_FILE,
        recent_db: str = DEFAULT_RECENT_DB,
    ):
        self.seen_file = seen_file
        os.makedirs(os.path.dirname(seen_file), exist_ok=True)
        self._seen: set[str] = self._load()
        self._recent_store = RecentArticleStore(db_path=recent_db)

    # ── Nivel 1: persistencia de hashes ─────────────────────────────────────

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
        return _article_url_hash(article) in self._seen

    def mark_seen(self, article: dict):
        h = _article_url_hash(article)
        self._seen.add(h)
        # También guardar hash de título normalizado
        title = article.get("title") or ""
        if title:
            self._seen.add(_title_hash(title))

    # ── API pública ──────────────────────────────────────────────────────────

    def deduplicate(self, articles: list[dict]) -> list[dict]:
        """
        Nivel 1 — Filtra artículos ya vistos por URL o título normalizado.
        Marca los nuevos como vistos y persiste.
        (La deduplicación semántica de Nivel 2 se aplica después de asignar el ticker,
        mediante check_semantic().)
        """
        new_articles = []
        for article in articles:
            url = (article.get("url") or article.get("link") or "").strip()
            title = article.get("title") or ""
            th = _title_hash(title)

            url_hash = _article_url_hash(article)

            if url_hash in self._seen:
                logger.info(
                    f"[DEDUP] Descartada por URL/título duplicado: {title[:60]}"
                )
                continue

            if th in self._seen:
                logger.info(
                    f"[DEDUP] Descartada por título idéntico: {title[:60]}"
                )
                continue

            new_articles.append(article)
            self.mark_seen(article)

        if new_articles:
            self._save()

        logger.info(
            f"Deduplicación Nivel 1: {len(articles)} entradas → {len(new_articles)} nuevas"
        )
        return new_articles

    def check_semantic(self, article: dict, ticker: str) -> bool:
        """
        Nivel 2 — Comprueba si el artículo es semánticamente duplicado de algún
        artículo reciente (últimas 48h) del mismo ticker.

        Devuelve True si es duplicado (debe descartarse), False si es nuevo.
        Cuando el artículo es nuevo, lo registra en la tienda de recientes.
        """
        title = article.get("title") or ""
        description = article.get("description") or article.get("summary") or ""

        # Comprobar primero por hash de título en la tienda reciente del ticker
        th = _title_hash(title)
        if self._recent_store.title_hash_exists(ticker, th):
            logger.info(
                f"[DEDUP] Descartada por título idéntico en últimas 48h [{ticker}]: {title[:60]}"
            )
            return True

        recent = self._recent_store.get_recent(ticker)
        is_dup, max_sim = is_duplicate_news(title, description, recent)

        if is_dup:
            logger.info(
                f"[DEDUP] Descartada por similitud ({max_sim:.2f}) [{ticker}]: {title[:60]}"
            )
            return True

        # Nueva noticia — registrar en la tienda de recientes
        self._recent_store.add(ticker, title, description)
        logger.info(f"[NEWS] Nueva noticia guardada [{ticker}]: {title[:60]}")
        return False

    def purge_old_recent(self):
        """Limpia artículos recientes más antiguos de la ventana de 48h."""
        self._recent_store.purge_old()
