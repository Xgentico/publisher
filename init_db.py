# init_db.py
from config import settings
import ledger  # import the module, not the function

def main():
    if not settings.postgres_url:
        raise RuntimeError("No PostgreSQL DSN configured. Set env vars and try again.")

    # Debug: show what's inside ledger right now
    print("Ledger module loaded. Available names:", [n for n in dir(ledger) if "schema" in n or "ledger" in n])

    # Call the function from the module
    ledger.ensure_schema(settings.postgres_url)
    print("Schema ensured. (claim_ledger table and indexes are ready.)")

if __name__ == "__main__":
    main()
