# reset_tables.py
from web.app import create_app
from web.models import db
from sqlalchemy import inspect, text

app = create_app()
with app.app_context():
    # Drop (if exist) in dependency order
    db.session.execute(text("DROP TABLE IF EXISTS chunk_generations CASCADE"))
    db.session.execute(text("DROP TABLE IF EXISTS project_chunks CASCADE"))
    db.session.execute(text("DROP TABLE IF EXISTS projects CASCADE"))
    db.session.commit()

    # Recreate with the patched models
    db.create_all()

    insp = inspect(db.engine)
    print("Tables now in DB:", insp.get_table_names())
