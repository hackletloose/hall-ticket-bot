# Ticket-Bot (Python, py-cord)

Dieser Bot implementiert ein Ticket-System für Discord in Python.  
Er unterstützt:
- Ticket-Erstellung per Button
- Ticket-Claim durch Supporter
- Schließen von Tickets
- Erstellung eines Transkripts
- Dedizierte Nur-Lesen-Rolle (@Ticket-Viewer / @Auditor)

## Voraussetzungen

- Python 3.8 oder höher
- Ein eingerichteter Bot in https://discord.com/developers/applications
- Ein Server, auf dem du den Bot hosten kannst (lokal oder in der Cloud)

## Installation

1. Repository klonen oder herunterladen.
2. Erstelle eine Datei `.env` basierend auf der Vorlage `.env.example`.
3. Passe die IDs (Rollen, Kanäle, Guild) und das Token an:
   ```bash
   BOT_TOKEN="DeinBotToken"
   GUILD_ID="1234567890"
   ...
