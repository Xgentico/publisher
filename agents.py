# agents.py
from crewai import Agent
from config import settings

def load_voice() -> str:
    try:
        return settings.brand_prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ("Write in a concise, science-grounded voice aligned with Dr. Melissa Hughes. "
                "Be warm and practical, but never compromise scientific accuracy.")

common_rules = (
    "You are authoring a neuroscience book. "
    "Science must be strictly factual from open-access, credible sources. "
    "Every factual claim requires an inline citation like [S1]. "
    "Creativity is allowed only in industry examples and metaphors."
)

def intake_planner():
    return Agent(
        role="Intake & Planner",
        goal=("Interpret user inputs (repurpose vs new). Define sections, research scope, and acceptance criteria "
              f"(≥{settings.min_citations_per_section} citations/section)."),
        backstory="A meticulous publishing PM for neuroscience titles.",
        verbose=True, allow_delegation=True, memory=True
    )

def researcher():
    return Agent(
        role="Researcher",
        goal=("Gather open-access neuroscience sources (Europe PMC / PubMed OA first). Produce APA-like refs and "
              "map source keys (S1..Sn) per section."),
        backstory="Precision researcher—no fabrications, no weak sources.",
        verbose=True
    )

def outliner():
    return Agent(
        role="Outliner",
        goal=("Turn the plan or TOC into a detailed outline. Mark which claims need which sources."),
        backstory="You create crisp, writeable outlines.",
        verbose=True
    )

def draft_writer():
    return Agent(
        role="Draft Writer",
        goal=("Write chapters in brand voice. Separate 'Core Science' and 'Industry Examples'. "
              "Tag every claim with [S#]."),
        backstory="Senior neuroscience writer with impeccable sourcing.",
        verbose=True, memory=True, constraints=[load_voice(), common_rules]
    )

def fact_checker():
    return Agent(
        role="Fact-Checker",
        goal=("Verify every claim against cited sources. Remove or fix unverifiable claims. "
              "Block progression if any section lacks required citations."),
        backstory="You prevent scientific errors from shipping.",
        verbose=True
    )

def plagiarism_guard():
    return Agent(
        role="Plagiarism Guard",
        goal=("Detect high similarity to source/onhand text and rewrite ≥ threshold while preserving meaning."),
        backstory="You ensure originality without losing accuracy.",
        verbose=True
    )

def qa_editor():
    return Agent(
        role="QA Editor",
        goal=("Polish style, headings, and references consistency."),
        backstory="You make manuscripts press-ready.",
        verbose=True
    )

def assembler():
    return Agent(
        role="Assembler",
        goal=("Assemble chapters and export DOCX with references."),
        backstory="You package final deliverables.",
        verbose=True
    )

def ledger_writer():
    return Agent(
        role="Ledger Writer",
        goal=("Scan the final fact-checked draft for claims with inline citations [S#] and produce "
              "a compact JSON (claim_payload.json) listing each section, the paragraph (claim_text), "
              "and the list of source_keys encountered."),
        backstory="You translate the validated manuscript into an auditable claim list.",
        verbose=True
    )