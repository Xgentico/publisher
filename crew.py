# crew.py
from crewai import Crew, Process
from agents import (
    intake_planner, researcher, outliner, draft_writer,
    fact_checker, plagiarism_guard, qa_editor, assembler,
    ledger_writer
)
from tasks import (
    task_plan, task_research, task_outline, task_draft,
    task_factcheck, task_plagiarism, task_qa, task_assemble,
    task_ledger
)

def build_crew():
    return Crew(
        agents=[
            intake_planner(),
            researcher(),
            outliner(),
            draft_writer(),
            fact_checker(),
            plagiarism_guard(),
            qa_editor(),
            ledger_writer(),   # <— added
            assembler()
        ],
        tasks=[
            task_plan(),
            task_research(),
            task_outline(),
            task_draft(),
            task_factcheck(),
            task_plagiarism(),
            task_qa(),
            task_ledger(),     # <— added
            task_assemble()
        ],
        process=Process.sequential,
        verbose=True
    )
