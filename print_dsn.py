from config import settings
import os, socket

print("POSTGRES_URL (built):", repr(settings.postgres_url))
print("POSTGRES_HOST:", repr(os.getenv("POSTGRES_HOST")))
print("DB_SSLMODE   :", repr(os.getenv("DB_SSLMODE")))

host = os.getenv("POSTGRES_HOST")
if host:
    try:
        print("DNS lookup:", socket.getaddrinfo(host, None))
    except Exception as e:
        print("DNS error  :", e)
