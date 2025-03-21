# utils/config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Fehler: BOT_TOKEN ist nicht gesetzt. Bitte in .env eintragen.")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID", "0"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
VIEWER_ROLE_ID = int(os.getenv("VIEWER_ROLE_ID", "0"))

CREATED_TICKETS_CATEGORY_ID = int(os.getenv("CREATED_TICKETS_CATEGORY_ID", "0"))
CLAIMED_TICKETS_CATEGORY_ID = int(os.getenv("CLAIMED_TICKETS_CATEGORY_ID", "0"))
CLOSED_TICKETS_CATEGORY_ID = int(os.getenv("CLOSED_TICKETS_CATEGORY_ID", "0"))

TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID", "0"))

MAX_TICKETS_PER_SUPPORTER = int(os.getenv("MAX_TICKETS_PER_SUPPORTER", "3"))
TICKET_CLEANUP_DAYS = int(os.getenv("TICKET_CLEANUP_DAYS", "7"))

