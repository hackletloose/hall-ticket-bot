import sqlite3

class Database:
    def __init__(self):
        # Erstelle Tabellen (falls nicht vorhanden)
        self._create_tables()
        self._ensure_admin_message_id_column()

    def _create_tables(self):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'open',
                    claimed_by TEXT,
                    user_name TEXT
                    -- admin_message_id kommt gleich per ALTER TABLE
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    transcript_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    transcript_content TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

            conn.commit()

    def _ensure_admin_message_id_column(self):
        """
        Versuche, per ALTER TABLE eine Spalte admin_message_id hinzuzufügen.
        Falls es sie schon gibt, ignorieren wir den Fehler.
        """
        with sqlite3.connect("tickets.sqlite") as conn:
            try:
                conn.execute("ALTER TABLE tickets ADD COLUMN admin_message_id TEXT")
                conn.commit()
                print("[DB] Spalte admin_message_id erfolgreich hinzugefügt.")
            except sqlite3.OperationalError:
                # Wahrscheinlich existiert die Spalte schon
                pass

    ########################################################################
    # Bot-Settings: key-value
    ########################################################################
    def save_bot_setting(self, key: str, value: str):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
                (key, value)
            )
            conn.commit()

    def get_bot_setting(self, key: str):
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
            row = cur.fetchone()
            if row:
                return row[0]
        return None

    ########################################################################
    # Ticket-Logik
    ########################################################################
    def get_next_ticket_id(self):
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM tickets")
            row = cur.fetchone()
            max_id = row[0] if row else 0
            return max_id + 1

    def insert_ticket(self, ticket_id, user_id, user_name, channel_id):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "INSERT INTO tickets (id, user_id, user_name, channel_id) VALUES (?, ?, ?, ?)",
                (ticket_id, str(user_id), user_name, str(channel_id))
            )
            conn.commit()

    def log_ticket_created(self, ticket_id: int, user_id: int, user_name: str, channel_id: int):
        self.insert_ticket(ticket_id, user_id, user_name, channel_id)
        print(f"[DB] Ticket erstellt - ID={ticket_id}, UserID={user_id}, Name='{user_name}', Channel={channel_id}")

    def log_ticket_admin_message(self, ticket_id: int, admin_message_id: int):
        """
        Speichert die Nachricht, in der die Admin-Buttons sind,
        damit wir sie reattachen können.
        """
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "UPDATE tickets SET admin_message_id=? WHERE id=?",
                (str(admin_message_id), ticket_id)
            )
            conn.commit()
        print(f"[DB] Ticket #{ticket_id}: admin_message_id={admin_message_id} hinterlegt.")

    def log_ticket_claimed(self, ticket_id: int, supporter_id: int):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "UPDATE tickets SET status='claimed', claimed_by=? WHERE id=?",
                (str(supporter_id), ticket_id)
            )
            conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde von Supporter {supporter_id} beansprucht.")

    def log_ticket_closed(self, ticket_id: int):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "UPDATE tickets SET status='closed' WHERE id=?",
                (ticket_id,)
            )
            conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde geschlossen.")

    def log_ticket_deleted(self, ticket_id: int):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "UPDATE tickets SET status='deleted' WHERE id=?",
                (ticket_id,)
            )
            conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde gelöscht.")

    def save_transcript(self, ticket_id: int, transcript_content: str):
        print(f"[DB] Speichere Transkript für Ticket #{ticket_id} in der DB ...")
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "INSERT INTO transcripts (ticket_id, transcript_content) VALUES (?, ?)",
                (ticket_id, transcript_content)
            )
            conn.commit()

    def get_transcript_by_ticket_id(self, ticket_id: int) -> str:
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT transcript_content FROM transcripts WHERE ticket_id=? ORDER BY transcript_id DESC LIMIT 1",
                (ticket_id,)
            )
            row = cur.fetchone()
            if row:
                return row[0]
        return ""

    def get_ticket_user(self, ticket_id: int):
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
            row = cur.fetchone()
            if row:
                return int(row[0])
        return None

    def get_open_or_claimed_tickets(self):
        """
        Liefert alle Tickets, die nicht 'closed' und nicht 'deleted' sind.
        Also Status = 'open' oder 'claimed'.
        """
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, channel_id, admin_message_id, status
                FROM tickets
                WHERE status IN ('open', 'claimed')
            """)
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "ticket_id": row[0],
                    "channel_id": row[1],
                    "admin_message_id": row[2],
                    "status": row[3]
                })
            return results
