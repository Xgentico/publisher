 # web/app.py
from __future__ import annotations
import os
import re
import json
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from sqlalchemy import text
from config import settings
from web.models import db, Project, ProjectChunk, ChunkGeneration
from web.services import load_brand_prompt, ensure_project_chunks, generate_for_chunk, latest_generation_map, write_artifacts_and_ledger

# --- Source handling helpers (drafts link, Word export strip) -----------------
TAG_PATTERN = re.compile(r"\[(S\d+)\]")               # [S1]
LINKED_PATTERN = re.compile(r"\[S\d+\]\([^)]+\)")     # [S1](https://...)
PLAIN_TAG_PATTERN = re.compile(r"\[S\d+\]")           # [S1]

def _link_sources_in_text(text: str, mapping: dict[str, str]) -> str:
    """Replace [S1] with [S1](URL) when URL exists; leave [S1] if not mapped."""
    if not mapping:
        return text
    def repl(m):
        tag = m.group(1)
        url = mapping.get(tag)
        return f"[{tag}]({url})" if url else f"[{tag}]"
    return TAG_PATTERN.sub(repl, text)

def _strip_sources_in_text(text: str) -> str:
    """Remove [S1](url) and bare [S1] for Word export."""
    text = LINKED_PATTERN.sub("", text)
    text = PLAIN_TAG_PATTERN.sub("", text)
    return " ".join(text.split())

def _load_sources_mapping(default_path: str = "sources.json") -> dict[str, str]:
    p = Path(os.getenv("SOURCES_FILE", default_path))
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")  # change in prod
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.postgres_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ✅ Robust Postgres connection handling on Render
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 5,
        "max_overflow": 5,
        "connect_args": {
            "sslmode": "require",
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
    }

    # Load default source mapping once (drafts will use it to link [S#])
    app.config["SOURCE_MAP"] = _load_sources_mapping()

    db.init_app(app)
    with app.app_context():
        db.create_all()  # creates projects, project_chunks, chunk_generations

    @app.route("/")
    def home():
        return redirect(url_for("projects"))

    @app.route("/projects")
    def projects():
        items = Project.query.order_by(Project.created_at.desc()).all()
        return render_template("projects_list.html", projects=items)

    @app.route("/projects/new", methods=["GET", "POST"])
    def project_new():
        if request.method == "POST":
            name = request.form.get("name", "").strip() or "Untitled Project"
            directions = request.form.get("directions", "").strip() or ""
            max_chars = int(request.form.get("max_chars", 1200))
            brand = load_brand_prompt()
            source_text = request.form.get("source_text", "")

            # Handle optional file upload
            f = request.files.get("source_file")
            if f and f.filename:
                try:
                    source_text = f.read().decode("utf-8")
                except Exception:
                    source_text = source_text or ""

            proj = Project(name=name, directions=directions, max_chars=max_chars, brand_prompt=brand, source_text=source_text)
            db.session.add(proj)
            db.session.commit()

            ensure_project_chunks(proj, re_chunk=True)
            return redirect(url_for("project_detail", project_id=proj.id))
        return render_template("project_create.html", default_brand=load_brand_prompt())

    @app.route("/projects/<project_id>")
    def project_detail(project_id):
        proj = Project.query.get_or_404(project_id)
        chunks = (ProjectChunk.query.filter_by(project_id=project_id).order_by(ProjectChunk.order_index).all())
        latest = latest_generation_map(project_id)
        return render_template("project_detail.html", project=proj, chunks=chunks, latest=latest)

    # ---- Directions tab
    @app.post("/projects/<project_id>/update_directions")
    def update_directions(project_id):
        proj = Project.query.get_or_404(project_id)
        proj.directions = request.form.get("directions", "")
        db.session.commit()
        flash("Directions updated.", "success")
        return redirect(url_for("project_detail", project_id=proj.id) + "#directions")

    # ---- Text to Convert tab
    @app.post("/projects/<project_id>/rechunk")
    def rechunk(project_id):
        proj = Project.query.get_or_404(project_id)
        proj.max_chars = int(request.form.get("max_chars", proj.max_chars))
        # update source text (paste area)
        pasted = request.form.get("source_text", None)
        if pasted is not None:
            proj.source_text = pasted
        db.session.commit()
        from web.services import ensure_project_chunks
        ensure_project_chunks(proj, re_chunk=True)
        flash("Re-chunked text.", "success")
        return redirect(url_for("project_detail", project_id=proj.id) + "#text")

    @app.post("/projects/<project_id>/toggle_select")
    def toggle_select(project_id):
        chunk_id = int(request.form["chunk_id"])
        ch = ProjectChunk.query.filter_by(project_id=project_id, id=chunk_id).first_or_404()
        ch.selected = not ch.selected
        db.session.commit()
        return redirect(url_for("project_detail", project_id=project_id) + "#text")

    # ---- Generation: per-chunk
    @app.post("/projects/<project_id>/generate/<int:chunk_id>")
    def generate_chunk(project_id, chunk_id):
        proj = Project.query.get_or_404(project_id)
        ch = ProjectChunk.query.filter_by(project_id=project_id, id=chunk_id).first_or_404()
        generate_for_chunk(proj, ch)
        flash(f"Generated text for chunk {ch.order_index+1}.", "success")
        return redirect(url_for("project_detail", project_id=proj.id) + "#generated")

    # ---- Generation: batch for selected
    @app.post("/projects/<project_id>/generate_batch")
    def generate_batch(project_id):
        proj = Project.query.get_or_404(project_id)
        chunks = ProjectChunk.query.filter_by(project_id=project_id, selected=True).order_by(ProjectChunk.order_index).all()
        for ch in chunks:
            generate_for_chunk(proj, ch)
        flash(f"Generated text for {len(chunks)} chunks.", "success")
        return redirect(url_for("project_detail", project_id=proj.id) + "#generated")

    # ---- Approve / Edit generated text
    @app.post("/projects/<project_id>/save_generation/<int:chunk_id>")
    def save_generation(project_id, chunk_id):
        proj = Project.query.get_or_404(project_id)
        ch = ProjectChunk.query.filter_by(project_id=project_id, id=chunk_id).first_or_404()
        text = request.form.get("generated_text", "").strip()
        approved = bool(request.form.get("approved"))

        # Linkify sources for drafts before saving (uses mapping loaded at startup)
        if text:
            linked_text = _link_sources_in_text(text, app.config.get("SOURCE_MAP", {}))
            gen = ChunkGeneration(project_id=proj.id, chunk_id=ch.id, generated_text=linked_text, sources=None)
            db.session.add(gen)

        ch.approved = approved
        db.session.commit()
        flash("Saved edits.", "success")
        return redirect(url_for("project_detail", project_id=proj.id) + "#generated")

    # ---- Assemble + download DOCX
    @app.post("/projects/<project_id>/assemble")
    def assemble_docx(project_id):
        proj = Project.query.get_or_404(project_id)
        out_docx = write_artifacts_and_ledger(proj)

        # Post-process the DOCX to strip any [S#](url) or [S#] before download.
        # If python-docx is unavailable, fall back to original file.
        cleaned_path = None
        try:
            from docx import Document
            doc = Document(out_docx)
            for para in doc.paragraphs:
                # Replace at run level to preserve formatting as much as possible
                for run in para.runs:
                    if run.text:
                        run.text = _strip_sources_in_text(run.text)
            cleaned_path = os.path.splitext(out_docx)[0] + ".clean.docx"
            doc.save(cleaned_path)
        except Exception:
            cleaned_path = None  # fallback to original

        flash("DOCX assembled and claims logged.", "success")
        return send_file(cleaned_path or out_docx, as_attachment=True, download_name=os.path.basename(cleaned_path or out_docx))

    # ---- Sources & Ledger tab (read-only)
    @app.get("/projects/<project_id>/ledger")
    def project_ledger(project_id):
        # Simple direct query to claim_ledger for this project
        sql = text("SELECT section, source_key, similarity_score, left(claim_text, 160) AS snippet, created_at "
                   "FROM claim_ledger WHERE project_id = :pid ORDER BY created_at DESC LIMIT 500")
        rows = db.session.execute(sql, {"pid": f"project::{project_id}"}).mappings().all()
        proj = Project.query.get_or_404(project_id)
        return render_template("project_ledger.html", project=proj, rows=rows)

    @app.route("/health", methods=["GET", "HEAD"])
    def health():
        return ("ok", 200, {"Content-Type": "text/plain"})

    return app

app = create_app()

