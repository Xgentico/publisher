# ledger.py
from __future__ import annotations
import json, re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Iterable, Tuple

import psycopg2
from psycopg2.extras import execute_batch
from rapidfuzz import fuzz

# ---------- Data models ----------

@dataclass
class LedgerRow:
    project_id: str
    section: str
    claim_text: str
    source_key: str
    source_citation: str
    similarity_score: Optional[float]  # 0..1
    created_at: datetime

# ---------- DB schema management ----------

DDL = """
CREATE TABLE IF NOT EXISTS claim_ledger (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    section TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_citation TEXT,
    similarity_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_project ON claim_ledger(project_id);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_section ON claim_ledger(section);
"""

def ensure_schema(pg_dsn: str):
    with psycopg2.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        conn.commit()

def insert_rows(pg_dsn: str, rows: List[LedgerRow]):
    if not rows:
        return
    with psycopg2.connect(pg_dsn) as conn, conn.cursor() as cur:
        execute_batch(
            cur,
            """
            INSERT INTO claim_ledger
            (project_id, section, claim_text, source_key, source_citation, similarity_score, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (r.project_id, r.section, r.claim_text, r.source_key, r.source_citation, r.similarity_score, r.created_at)
                for r in rows
            ],
            page_size=200
        )
        conn.commit()

# ---------- Parsing draft & sources ----------

H1 = re.compile(r"^#\s+(.*)")
H2 = re.compile(r"^##\s+(.*)")
SRC_KEYS = re.compile(r"\[(S\d+)\]")  # matches [S1], [S12], etc.

def _iter_paragraphs(md_text: str) -> Iterable[Tuple[str, str]]:
    """
    Yields (section_path, paragraph_text)
    section_path like "Chapter Title > Section Title"
    """
    lines = md_text.splitlines()
    h1, h2 = None, None
    buf: List[str] = []

    def flush():
        nonlocal buf
        if buf:
            para = "\n".join(buf).strip()
            if para:
                section_path = " > ".join([p for p in [h1, h2] if p])
                yield (section_path or "ROOT", para)
        buf = []

    for ln in lines:
        m1, m2 = H1.match(ln), H2.match(ln)
        if m1:
            yield from flush()
            h1, h2 = m1.group(1).strip(), None
            continue
        if m2:
            yield from flush()
            h2 = m2.group(1).strip()
            continue
        if ln.strip() == "":
            yield from flush()
        else:
            buf.append(ln)
    yield from flush()

def extract_claims(md_text: str) -> List[Tuple[str, str, List[str]]]:
    """
    Returns list of (section_path, paragraph_text, [source_keys])
    """
    claims: List[Tuple[str, str, List[str]]] = []
    for section, para in _iter_paragraphs(md_text):
        keys = list(dict.fromkeys(SRC_KEYS.findall(para)))  # preserve order, unique
        if keys:
            claims.append((section, para, keys))
    return claims

# ---------- Similarity scoring ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def similarity(a: str, b: Optional[str]) -> Optional[float]:
    if not b:
        return None
    return fuzz.token_set_ratio(_norm(a), _norm(b)) / 100.0

# ---------- Sources loader ----------

def load_sources_maps(sources_json_path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Returns:
      references_map: { 'S1': 'APA string', ... }
      abstracts_map : { 'S1': 'abstract/fulltext snippet', ... }
    Expected JSON structure from Researcher step:
      [{ "key":"S1", "title":"...", "url":"...", "doi":"...", "year":2020, "abstract":"..." }, ...]
    """
    with open(sources_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    references_map: Dict[str, str] = {}
    abstracts_map: Dict[str, str] = {}
    for it in data:
        key = it.get("key")
        if not key:
            continue
        title = it.get("title") or "Untitled"
        year = it.get("year")
        doi = it.get("doi")
        url = it.get("url")
        apa = f"({year}) {title}. " if year else f"{title}. "
        if doi:
            apa += f"https://doi.org/{doi}"
        elif url:
            apa += url
        references_map[key] = apa
        abstracts_map[key] = it.get("abstract") or ""
    return references_map, abstracts_map

# ---------- Main entry ----------

def log_claims_from_markdown(
    pg_dsn: str,
    project_id: str,
    draft_md_path: str,
    sources_json_path: str
) -> int:
    """
    Parses the draft markdown, extracts claims + [S#],
    computes similarity vs. source abstracts, and inserts rows.
    Returns number of rows inserted.
    """
    ensure_schema(pg_dsn)

    with open(draft_md_path, "r", encoding="utf-8") as f:
        md = f.read()

    references_map, abstracts_map = load_sources_maps(sources_json_path)
    claims = extract_claims(md)

    now = datetime.now(timezone.utc)
    rows: List[LedgerRow] = []
    for section, para, keys in claims:
        for key in keys:
            rows.append(
                LedgerRow(
                    project_id=project_id,
                    section=section,
                    claim_text=para,
                    source_key=key,
                    source_citation=references_map.get(key, ""),
                    similarity_score=similarity(para, abstracts_map.get(key)),
                    created_at=now
                )
            )

    insert_rows(pg_dsn, rows)
    return len(rows)
