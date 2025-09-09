# check_models.py
from web.app import create_app
from web.models import db
from sqlalchemy import inspect

app = create_app()
with app.app_context():
    insp = inspect(db.engine)
    print("Tables in DB:", insp.get_table_names())
