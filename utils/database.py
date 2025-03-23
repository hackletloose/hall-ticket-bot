# utils/database.py
import sqlite3
import os

class Database:
    def __init__(self):
        # Erstelle Tabellen (falls nicht vorhanden), ohne globale Connection zu behalten
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'open',
                    claimed_by TEXT
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
            conn.commit()

    def get_next_ticket_id(self):
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM tickets")
            row = cur.fetchone()
            max_id = row[0] if row else 0
            return max_id + 1

    def insert_ticket(self, ticket_id, user_id, channel_id):
        with sqlite3.connect("tickets.sqlite") as conn:
            conn.execute(
                "INSERT INTO tickets (id, user_id, channel_id) VALUES (?, ?, ?)",
                (ticket_id, str(user_id), str(channel_id))
            )
            conn.commit()

    def log_ticket_created(self, ticket_id: int, user_id: int, channel_id: int):
        self.insert_ticket(ticket_id, user_id, channel_id)
        print(f"[DB] Ticket erstellt - ID={ticket_id}, User={user_id}, Channel={channel_id}")

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
                return row[0]  # transcript_content
        return ""

    def get_ticket_user(self, ticket_id: int):
        with sqlite3.connect("tickets.sqlite") as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
            row = cur.fetchone()
            if row:
                return int(row[0])
        return None
