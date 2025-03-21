# utils/database.py
import sqlite3
import os

class Database:
    def __init__(self):
        self.conn = sqlite3.connect("tickets.sqlite")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'open',
                claimed_by TEXT
            );
        """)
        self.conn.commit()

    def get_next_ticket_id(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM tickets")
        row = cur.fetchone()
        max_id = row[0] if row else 0
        return max_id + 1

    def insert_ticket(self, ticket_id, user_id, channel_id):
        self.conn.execute(
            "INSERT INTO tickets (id, user_id, channel_id) VALUES (?, ?, ?)",
            (ticket_id, str(user_id), str(channel_id))
        )
        self.conn.commit()

    def log_ticket_created(self, ticket_id: int, user_id: int, channel_id: int):
        self.insert_ticket(ticket_id, user_id, channel_id)
        print(f"[DB] Ticket erstellt - ID={ticket_id}, User={user_id}, Channel={channel_id}")

    def log_ticket_claimed(self, ticket_id: int, supporter_id: int):
        self.conn.execute(
            "UPDATE tickets SET status='claimed', claimed_by=? WHERE id=?",
            (str(supporter_id), ticket_id)
        )
        self.conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde von Supporter {supporter_id} beansprucht.")

    def log_ticket_closed(self, ticket_id: int):
        self.conn.execute(
            "UPDATE tickets SET status='closed' WHERE id=?",
            (ticket_id,)
        )
        self.conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde geschlossen.")

    def log_ticket_deleted(self, ticket_id: int):
        self.conn.execute(
            "UPDATE tickets SET status='deleted' WHERE id=?",
            (ticket_id,)
        )
        self.conn.commit()
        print(f"[DB] Ticket #{ticket_id} wurde gelöscht.")

    def save_transcript(self, ticket_id: int, transcript_content: str):
        print(f"[DB] Speichere Transkript für Ticket #{ticket_id}")
        os.makedirs("data", exist_ok=True)
        with open(f"data/transcript_{ticket_id}.txt", "w", encoding="utf-8") as f:
            f.write(transcript_content)

    def get_ticket_user(self, ticket_id: int):
        cur = self.conn.cursor()
        cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
        row = cur.fetchone()
        if row:
            return int(row[0])
        return None
