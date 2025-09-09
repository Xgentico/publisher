 # web/services.py
from __future__ import annotations
from typing import List, Dict, Tuple
from pathlib import Path
import re, json, os  # <- added os

from config import settings, get_openai_client
from tools import build_sources_for_neuro, apa_citation
from web.models import db, Project, ProjectChunk, ChunkGeneration
from .assemble import assemble_to_docx

PARA_SPLIT = re.compile(r"\n\s*\n+")  # split on empty lines

# --- Minimal domain lexicon & detector --------------------------------------
HEALTHCARE_TERMS = [
    "patient", "clinician", "provider", "care team", "care pathway", "clinical workflow",
    "EHR", "EMR", "HIPAA", "ICU", "triage", "ambulatory", "inpatient",
    "diagnostic", "therapeutic", "clinical decision-making", "protocol",
    "rounds", "charting", "order set", "QALY", "outcome measure", "readmission",
    "medication adherence", "comorbidity", "care coordination"
]

def detect_target_industry(directions: str) -> str:
    d = (directions or "").lower()
    if "healthcare" in d or "health care" in d or "clinical" in d or "hospital" in d:
        return "healthcare"
    return "general"

def count_lexicon_hits(text: str, lexicon: List[str]) -> int:
    t = text.lower()
    return sum(1 for term in lexicon if term.lower() in t)

# ---------------------------------------------------------------------------

def load_brand_prompt() -> str:
    try:
        return settings.brand_prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "Write in a concise, science-grounded, practical voice. No hype."

def chunk_text(text: str, max_chars: int = 1200) -> List[str]:
    """Split by paragraphs, then merge small paragraphs up to max_chars."""
    paras = [p.strip() for p in PARA_SPLIT.split(text or "") if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf = f"{buf}\n\n{p}"
        else:
            chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks

def ensure_project_chunks(project: Project, re_chunk: bool = False):
    if not project.source_text:
        return
    if re_chunk:
        ProjectChunk.query.filter_by(project_id=project.id).delete()
        db.session.commit()
    if ProjectChunk.query.filter_by(project_id=project.id).count() == 0:
        parts = chunk_text(project.source_text, project.max_chars)
        for idx, part in enumerate(parts):
            db.session.add(ProjectChunk(project_id=project.id, order_index=idx, source_text=part))
        db.session.commit()

# --- Prompt: explicit industry focus + checklist ----------------------------
PROMPT_TMPL = """You are a neuroscience author. Follow these rules strictly:
- Ground every scientific statement in the provided sources; do not fabricate or overclaim.
- Use inline citations like [S1], [S2] that match the Source Keys.
- Preserve scientific mechanisms/claims exactly; adapt only framing, examples, and metaphors.
- Brand voice (guidance): {brand_voice}

Industry Focus: {industry_upper}
Directions (project brief):
{directions}

CHECKLIST (must satisfy before returning):
1) The tone and examples MUST reflect the **{industry_upper}** domain.
2) Include at least {min_hits} terms from this domain lexicon: {lexicon_list}
3) Keep all inline citations [S#] intact and aligned to claims.
4) If sources are insufficient for a claim, explicitly say so and stop.

Source chunk to repurpose:
\"\"\"{chunk_text}\"\"\"

Open-access neuroscience sources you can cite (keys for [S#]):
{sources_block}

Write 1–2 crisp paragraphs adapted for **{industry_upper}** with [S#] citations.
"""

def _sources_block(sources: List[Dict]) -> str:
    lines = []
    for s in sources:
        lines.append(f"- {s.get('key')}: {s.get('title')} | {s.get('url') or ('https://doi.org/'+s.get('doi',''))}")
    return "\n".join(lines)

# --- Style enforcer post-pass ----------------------------------------------
REWRITE_TMPL = """Revise the text to better fit the **{industry_upper}** domain, while preserving meaning and ALL [S#] citations.
Use at least {min_hits} terms from this lexicon: {lexicon_list}
Do not add new scientific claims. Do not remove or renumber citations.

Original:
\"\"\"{text}\"\"\"

Return only the revised text.
"""

def enforce_industry_style(text: str, industry: str, min_hits: int, lexicon: List[str]) -> str:
    """If the text lacks enough domain language, rewrite to inject domain metaphors/terms."""
    if industry != "healthcare":
        return text  # only enforcing healthcare for now
    hits = count_lexicon_hits(text, lexicon)
    if hits >= min_hits:
        return text

    client = get_openai_client()
    prompt = REWRITE_TMPL.format(
        industry_upper=industry.upper(),
        min_hits=min_hits,
        lexicon_list=", ".join(lexicon),
        text=text
    )
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You are a precise editor. Preserve meaning and citations exactly while localizing tone/terminology."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    revised = resp.choices[0].message.content.strip()
    # Final sanity: keep original if somehow citations got dropped
    if "[S" not in revised and "[s" not in revised:
        return text
    return revised

# ---------------------------------------------------------------------------

def generate_for_chunk(project: Project, chunk: ProjectChunk) -> Tuple[str, List[Dict]]:
    # Detect target industry from directions (no DB changes required)
    industry = detect_target_industry(project.directions)
    min_hits = 2 if industry == "healthcare" else 0
    lexicon = HEALTHCARE_TERMS if industry == "healthcare" else []

    # 1) Fetch sources (OA-first) with guard (Option 2)
    try:
        srcs = build_sources_for_neuro(chunk.source_text, need=3)
    except Exception as e:
        print("Source build failed:", e)
        srcs = []
    srcs_dicts = [s.__dict__ for s in srcs]

    # 2) Build brand voice
    brand = project.brand_prompt or load_brand_prompt()

    # Switch to CrewAI if enabled
    USE_CREWAI = os.getenv("USE_CREWAI", "false").lower() in ("1", "true", "yes")
    if USE_CREWAI:
        from crew.workflow import run_generation_with_crew
        text = run_generation_with_crew(
            brand_voice=brand,
            directions=project.directions or "",
            industry=industry,
            chunk_text=chunk.source_text,
            sources=srcs_dicts,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )
        # Enforce industry style if needed
        text = enforce_industry_style(text, industry, min_hits=min_hits, lexicon=lexicon)
    else:
        # 2) Build prompt
        prompt = PROMPT_TMPL.format(
            brand_voice=brand,
            directions=project.directions or "",
            industry_upper=industry.upper(),
            min_hits=min_hits,
            lexicon_list=", ".join(lexicon) if lexicon else "(none)",
            chunk_text=chunk.source_text,
            sources_block=_sources_block(srcs_dicts)
        )

        # 3) Call OpenAI
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are a meticulous neuroscience author who cites sources and never fabricates."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.35,
        )
        text = resp.choices[0].message.content.strip()

        # 4) Enforce industry style if needed
        text = enforce_industry_style(text, industry, min_hits=min_hits, lexicon=lexicon)

    # 5) Save generation
    gen = ChunkGeneration(
        project_id=project.id,
        chunk_id=chunk.id,
        generated_text=text,
        sources=srcs_dicts
    )
    db.session.add(gen)
    db.session.commit()
    return text, srcs_dicts

def latest_generation_map(project_id: str) -> Dict[int, ChunkGeneration]:
    rows = (ChunkGeneration.query
            .filter_by(project_id=project_id)
            .order_by(ChunkGeneration.created_at.desc())
            .all())
    latest: Dict[int, ChunkGeneration] = {}
    for r in rows:
        if r.chunk_id not in latest:
            latest[r.chunk_id] = r
    return latest

def write_artifacts_and_ledger(project: Project) -> Path:
    latest = latest_generation_map(project.id)
    parts = []
    for ch in ProjectChunk.query.filter_by(project_id=project.id).order_by(ProjectChunk.order_index).all():
        g = latest.get(ch.id)
        if g and (ch.approved or True):
            parts.append(g.generated_text.strip())
    final_md_text = "\n\n".join(parts).strip() or "# Empty\n\n(No generated content yet.)"

    proj_dir = settings.artifacts_dir / project.id
    proj_dir.mkdir(parents=True, exist_ok=True)
    final_md_path = proj_dir / "final.md"
    final_md_path.write_text(final_md_text, encoding="utf-8")

    seen = {}
    for g in latest.values():
        for s in (g.sources or []):
            seen[s["key"]] = s
    sources_json_path = proj_dir / "sources.json"
    sources_json_path.write_text(json.dumps(list(seen.values()), indent=2), encoding="utf-8")

    #from assemble import assemble_to_docx
    out_docx = settings.output_dir / f"{project.name or 'manuscript'}_{project.id}.docx"
    assemble_to_docx(final_md_path, sources_json_path, out_docx)

    from ledger import log_claims_from_markdown
    log_claims_from_markdown(
        pg_dsn=settings.postgres_url,
        project_id=f"project::{project.id}",
        draft_md_path=str(final_md_path),
        sources_json_path=str(sources_json_path)
    )
    return out_docx
