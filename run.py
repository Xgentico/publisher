# run.py
from crew import build_crew
from config import settings
from pathlib import Path

# NEW: import ledger helper
from ledger import log_claims_from_markdown

def gather_inputs():
    mode = input("Mode [repurpose|new]: ").strip().lower()
    brand = settings.brand_prompt_path.read_text(encoding="utf-8") if settings.brand_prompt_path.exists() else ""
    payload = {"brand_voice": brand, "domain": "neuroscience"}

    if mode == "repurpose":
        payload["mode"] = "repurpose"
        payload["target_industry"] = input("Target industry (e.g., Healthcare): ").strip()
        src_path = input(f"Path to original text [{settings.input_dir/'original_book.txt'}]: ").strip() \
                   or str(settings.input_dir / "original_book.txt")
        payload["source_text"] = open(src_path, "r", encoding="utf-8").read()
    else:
        payload["mode"] = "new"
        toc_path = input(f"Path to TOC markdown [{settings.input_dir/'sample_toc.md'}]: ").strip() \
                   or str(settings.input_dir / "sample_toc.md")
        payload["toc"] = open(toc_path, "r", encoding="utf-8").read()

    payload["min_citations_per_section"] = settings.min_citations_per_section
    payload["max_similarity_ratio"] = settings.max_similarity_ratio
    return payload

def _maybe_log_to_ledger(project_id: str):
    """
    Looks for artifacts and logs to Postgres if configured:
      - sources.json   (from Researcher task)
      - factchecked.md or final.md (prefers final.md)
    """
    if not settings.postgres_url:
        print("Ledger: PostgreSQL DSN not configured; skipping claim logging.")
        return

    artifacts = settings.artifacts_dir
    sources_json = artifacts / "sources.json"
    draft_md = artifacts / "final.md"
    if not draft_md.exists():
        draft_md = artifacts / "factchecked.md"

    if not (sources_json.exists() and draft_md.exists()):
        print(f"Ledger: missing inputs (sources_json={sources_json.exists()}, draft_md={draft_md.exists()}); skipping.")
        return

    try:
        n = log_claims_from_markdown(
            pg_dsn=settings.postgres_url,
            project_id=project_id,
            draft_md_path=str(draft_md),
            sources_json_path=str(sources_json)
        )
        print(f"Ledger: inserted {n} claim rows.")
    except Exception as e:
        print(f"Ledger: ERROR logging claims: {e}")

def main():
    payload = gather_inputs()
    # Create a simple project_id
    proj_suffix = payload.get("target_industry", payload["mode"])
    project_id = f"publishing_crew::{payload['domain']}::{proj_suffix}"

    crew = build_crew()
    result = crew.kickoff(inputs=payload)
    print("\n--- RESULT ---\n")
    print(result)

    # After crew finishes, attempt to log claims
    _maybe_log_to_ledger(project_id)

if __name__ == "__main__":
    main()
