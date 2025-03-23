# utils/config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Fehler: BOT_TOKEN ist nicht gesetzt. Bitte in .env eintragen.")

# Bereits vorhandene Variablen
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
SUPPORT_ROLE_ID = os.getenv("SUPPORT_ROLE_ID", "0")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID", "0")
VIEWER_ROLE_ID = os.getenv("VIEWER_ROLE_ID", "0")
VIEWER2_ROLE_ID = os.getenv("VIEWER2_ROLE_ID", "0")

CREATED_TICKETS_CATEGORY_ID = int(os.getenv("CREATED_TICKETS_CATEGORY_ID", "0"))
CLAIMED_TICKETS_CATEGORY_ID = int(os.getenv("CLAIMED_TICKETS_CATEGORY_ID", "0"))
CLOSED_TICKETS_CATEGORY_ID = int(os.getenv("CLOSED_TICKETS_CATEGORY_ID", "0"))
TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID", "0"))
MAX_TICKETS_PER_SUPPORTER = int(os.getenv("MAX_TICKETS_PER_SUPPORTER", "3"))
TICKET_CLEANUP_DAYS = int(os.getenv("TICKET_CLEANUP_DAYS", "7"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Warnung: OPENAI_API_KEY ist nicht gesetzt. Die KI-Funktion kann nicht verwendet werden.")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

# Neu: Flask-Secret
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "CHANGEME")

# Neu: Discord OAuth2
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "")

# Da wir nur String-Vergleiche brauchen, konvertieren wir Rollen zu Strings:
# (Discord liefert Rollen als Strings, also "11111111", etc.)
ALLOWED_ROLES = [
    SUPPORT_ROLE_ID.strip(),
    ADMIN_ROLE_ID.strip(),
    VIEWER_ROLE_ID.strip(),
    VIEWER2_ROLE_ID.strip()
]
