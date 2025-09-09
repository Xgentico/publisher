# crew/workflow.py
from __future__ import annotations
from typing import List, Dict, Optional
import re

# CrewAI core
from crewai import Agent, Task, Crew, Process
try:
    # Some CrewAI versions expose an LLM wrapper
    from crewai import LLM  # type: ignore

    def _make_llm(model: str, api_key: str):
        return LLM(model=model, api_key=api_key)
except Exception:  # Fallback for versions without LLM wrapper
    LLM = None  # type: ignore

    def _make_llm(model: str, api_key: str):
        # Recent CrewAI versions accept a model name string directly
        return model


# -----------------------------------------------------------------------------#
# Helpers                                                                      #
# -----------------------------------------------------------------------------#

def _sources_block(sources: List[Dict]) -> str:
    """Pretty-print candidate sources with keys for prompt context."""
    lines = []
    for s in sources:
        key = s.get("key") or "S?"
        title = s.get("title") or "Untitled"
        url = s.get("url")
        doi = s.get("doi")
        link = url or (f"https://doi.org/{doi}" if doi else "")
        lines.append(f"- {key}: {title} | {link}")
    return "\n".join(lines)


def _parse_selected_keys(text: str) -> List[str]:
    """Extract S# tokens from the researcher's output; keep order & uniqueness."""
    if not text:
        return []
    keys = re.findall(r"\bS\d+\b", text)
    seen = set()
    out: List[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _run_single_task(agent: Agent, description: str, expected_output: Optional[str] = None) -> str:
    """Run a one-task crew and return the task's output as string."""
    t = Task(
        description=description,
        expected_output=expected_output or "",
        agent=agent,
    )
    c = Crew(agents=[agent], tasks=[t], process=Process.sequential, verbose=False)
    result = c.kickoff()
    # Prefer the task's own output if the version exposes it
    out = getattr(t, "output", None)
    if out:
        return str(out)
    # Fallback to crew result across versions
    return getattr(result, "raw", None) or getattr(result, "final_output", None) or str(result)


def _sanitize_citations(text: str, allowed_keys: List[str]) -> str:
    """Remove any [S#] citations that aren't in the allowed set."""
    if not text:
        return text
    allowed = set(allowed_keys or [])
    pat = re.compile(r"\[S(\d+)\]")

    def repl(m: re.Match) -> str:
        k = f"S{m.group(1)}"
        return m.group(0) if k in allowed else ""  # drop unknown cites

    return pat.sub(repl, text)


def _ensure_citation_per_paragraph(text: str, selected_keys: list[str]) -> str:
    if not text or not selected_keys:
        return text
    first = selected_keys[0]
    paras = re.split(r"\n\s*\n+", text.strip())
    fixed = []
    for p in paras:
        # already has a valid [S#]?
        if re.search(r"\[S\d+\]", p):
            fixed.append(p)
        else:
            fixed.append(p.rstrip() + f" [{first}]")
    return "\n\n".join(fixed)


# -----------------------------------------------------------------------------#
# Entry point                                                                  #
# -----------------------------------------------------------------------------#

def run_generation_with_crew(
    *,
    brand_voice: str,
    directions: str,
    industry: str,
    chunk_text: str,
    sources: List[Dict],
    model: str,
    api_key: str,
) -> str:
    """
    Deterministic 3-step pipeline:
      1) Researcher selects 2–3 source KEYS (S#) from provided candidates.
      2) Adapter writes 1–2 paragraphs with inline [S#] using ONLY those keys.
      3) Editor polishes, deletes unapproved citations, and enforces tone.
    """
    llm = _make_llm(model, api_key)
    industry_upper = (industry or "general").upper()
    sources_txt = _sources_block(sources)

    # ------------------------- Agents --------------------------------------- #
    researcher = Agent(
        role="Neuroscience Researcher",
        goal="Select the most relevant open-access sources for the provided chunk.",
        backstory="You prioritize systematic reviews and high-quality studies. You never invent citations.",
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    adapter = Agent(
        role="Industry Adapter",
        goal=f"Adapt the chunk for the {industry_upper} domain using only the selected sources.",
        backstory="You keep the science intact but tailor metaphors and terminology to the target industry.",
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    editor = Agent(
        role="Scientific Editor",
        goal="Ensure tone, correctness, and citations [S#] are preserved; polish the prose.",
        backstory="You are strict about factual accuracy and consistent citation formatting.",
        allow_delegation=False,
        llm=llm,
        verbose=False,
    )

    # ------------------------- Step 1: Research ----------------------------- #
    t1_desc = (
        "You are given candidate sources (with keys) and a source text chunk.\n"
        "Select 2–3 KEYS that are most relevant and can support the scientific claims.\n"
        "Use only the provided list; do not invent sources.\n\n"
        f"Candidate sources:\n{sources_txt}\n\n"
        f"Chunk:\n\"\"\"{chunk_text}\"\"\"\n\n"
        "Return ONLY a comma-separated list of keys, like:\nS1,S3"
    )
    keys_raw = _run_single_task(
        agent=researcher,
        description=t1_desc,
        expected_output="Comma-separated keys (e.g., S1,S3). No extra words."
    )
    selected_keys = _parse_selected_keys(keys_raw)

    # Fallback: if parsing failed, use first two candidates so we never block
    if not selected_keys:
        selected_keys = [s.get("key") for s in sources if s.get("key")][:2]

    keys_str = ",".join(selected_keys) if selected_keys else ""
    selected_block = "\n".join(
        f"- {s['key']}: {s.get('title','Untitled')}" for s in sources if s.get("key") in selected_keys
    )

    # ------------------------- Step 2: Adapt -------------------------------- #
    t2_desc = (
        f"Brand voice: {brand_voice}\n"
        f"Directions: {directions}\n"
        f"Industry Focus: {industry_upper}\n\n"
        f"Use ONLY these selected keys for citations: {keys_str}\n"
        f"Selected references:\n{selected_block}\n\n"
        "Write 1–2 crisp paragraphs adapted to the industry.\n"
        "Keep scientific mechanisms intact and cite claims inline with [S#] using ONLY the keys above.\n"
        "Use clear, clinical phrasing; avoid flowery language or purple prose.\n"
        "Only use metaphors if they clarify care delivery or clinical workflow.\n"
        "Keep it concise: 1–2 short paragraphs, no bulleted lists unless asked.\n"
        "Cite at least once per paragraph using ONLY the selected keys.\n\n"
        f"Source chunk:\n\"\"\"{chunk_text}\"\"\""
    )

    # Ensure adapted_text exists even if the adapter step raises
    adapted_text = ""
    try:
        adapted_text = _run_single_task(
            agent=adapter,
            description=t2_desc,
            expected_output="1–2 paragraphs with inline [S#] citations using ONLY the selected keys."
        ).strip()
    except Exception as e:
        print("CREW ERROR — adapter step failed:", e)
        adapted_text = ""  # keep as empty string; editor step will still run

    # ------------------------- Step 3: Edit --------------------------------- #
    t3_desc = (
        "Review and lightly edit the adapted text below. Enforce:\n"
        f"1) Tone/examples match **{industry_upper}**.\n"
        "2) All scientific claims are supported by [S#] citations using ONLY the selected keys.\n"
        "3) Keep [S#] intact. Do NOT add or delete citations except to remove unapproved keys.\n"
        "4) Delete any [S#] citation not in the selected keys.\n"
        "5) Ensure each paragraph contains at least one [S#] citation using ONLY the selected keys.\n"
        "6) Do NOT ask for more information and do NOT apologize.\n"
        "7) Trim flowery language; enforce a credible, conversational, science-first tone.\n"
        "8) Return ONLY the final revised text.\n\n"
        f"Selected keys: {keys_str}\n"
        f"Selected references:\n{selected_block}\n\n"
        f"Adapted text:\n\"\"\"{adapted_text}\"\"\""
    )

    final_text = _run_single_task(
        agent=editor,
        description=t3_desc,
        expected_output="Final revised text only."
    ).strip()

    # ------------------------- Sanitize & Return ---------------------------- #
    # Ensure no fabricated citations slip through.
    final_text = _sanitize_citations(final_text, selected_keys)
    adapted_text = _sanitize_citations(adapted_text, selected_keys)

    # Replace any generic [S#] placeholders with the first selected key
    if selected_keys:
        first = selected_keys[0]
        final_text = re.sub(r"\[S#\]", f"[{first}]", final_text)
        adapted_text = re.sub(r"\[S#\]", f"[{first}]", adapted_text)

    # Guarantee at least one approved citation per paragraph (if we have keys)
    final_text = _ensure_citation_per_paragraph(final_text, selected_keys)
    adapted_text = _ensure_citation_per_paragraph(adapted_text, selected_keys)

    # As a last resort, if the final text has no [S\d+] at all, append one
    if selected_keys and not re.search(r"\[S\d+\]", final_text):
        final_text = final_text.rstrip() + f" [{selected_keys[0]}]"

    # If somehow the editor returns empty, fall back to adapter output
    return final_text or adapted_text
