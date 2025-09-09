# web/models.py
from __future__ import annotations
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from uuid import uuid4
from sqlalchemy import func, Text, Boolean, Integer, JSON

db = SQLAlchemy()

def new_uuid() -> str:
    return str(uuid4())  # "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)  # <-- string UUID
    name = db.Column(db.String(200), nullable=False)
    directions = db.Column(Text, nullable=True)
    brand_prompt = db.Column(Text, nullable=True)
    source_text = db.Column(Text, nullable=True)
    max_chars = db.Column(Integer, nullable=False, default=1200)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = db.relationship("ProjectChunk", backref="project", lazy=True, cascade="all, delete-orphan")

class ProjectChunk(db.Model):
    __tablename__ = "project_chunks"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id"), nullable=False, index=True)  # <-- string FK
    order_index = db.Column(Integer, nullable=False, index=True)
    source_text = db.Column(Text, nullable=False)
    selected = db.Column(Boolean, nullable=False, default=True)
    approved = db.Column(Boolean, nullable=False, default=False)

    generations = db.relationship("ChunkGeneration", backref="chunk", lazy=True, cascade="all, delete-orphan")

class ChunkGeneration(db.Model):
    __tablename__ = "chunk_generations"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id"), nullable=False, index=True)  # <-- string FK
    chunk_id = db.Column(db.Integer, db.ForeignKey("project_chunks.id"), nullable=False, index=True)
    generated_text = db.Column(Text, nullable=False)
    sources = db.Column(JSON, nullable=True)  # [{"key":"S1","title":"...","url":"...","doi":"...","year":2024,"abstract":"..."}]
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
