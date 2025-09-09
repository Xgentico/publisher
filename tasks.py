# tasks.py
from crewai import Task
from config import settings

def task_plan():
    return Task(
        description=("Identify mode (repurpose vs new). "
                     "Repurpose: list core science to preserve; define industry-specific example tracks. "
                     "New: transform TOC into a section plan. "
                     f"Set min citations/section = {settings.min_citations_per_section}. "
                     "Output JSON plan with sections and acceptance criteria."),
        expected_output="plan.json"
    )

def task_research():
    return Task(
        description=("For each section, gather ≥ required open-access neuroscience sources. "
                     "Return keys S1..Sn, titles, URLs/DOIs, abstracts if available, and section→sources mapping."),
        expected_output="sources.json"
    )

def task_outline():
    return Task(
        description=("Produce a Markdown outline linking outline bullets to source keys that will support them."),
        expected_output="outline.md"
    )

def task_draft():
    return Task(
        description=("Write chapter drafts in brand voice. "
                     "Every factual paragraph ends with inline [S#] citations. "
                     "Use two subsections per section: 'Core Science' and 'Industry Examples'."),
        expected_output="draft.md"
    )

def task_factcheck():
    return Task(
        description=("Check all claims vs sources. Remove or fix unverifiable claims. "
                     "Ensure each section meets the citation threshold."),
        expected_output="factchecked.md"
    )

def task_plagiarism():
    return Task(
        description=("Compare draft paragraphs to provided sources and original input text. "
                     f"Rewrite any paragraph with similarity > {int(settings.max_similarity_ratio*100)}%. "
                     "Produce similarity_report.json."),
        expected_output="deplagiarized.md"
    )

def task_qa():
    return Task(
        description=("Final style pass; heading levels; consistent references section."),
        expected_output="final.md"
    )

def task_assemble():
    return Task(
        description=("Convert final Markdown structure to a structured chapter payload and export to DOCX. "
                     "Return file path."),
        expected_output="path_to_docx"
    )


def task_ledger():
    return Task(
        description=("Extract claims from the fact-checked draft (lines containing [S#]) and prepare a JSON payload "
                     "of {section, claim_text, source_keys[]} so the runner can log them to PostgreSQL. "
                     "Name the file claim_payload.json and write it to outputs/artifacts."),
        expected_output="claim_payload.json"
    )