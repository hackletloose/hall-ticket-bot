---

# Ticket-Bot & Web-Panel (Discord + Flask)

Dies ist ein Discord-Ticket-Bot mit integrierter KI-Unterstützung (OpenAI GPT-3.5). Der Bot ermöglicht Nutzer\*innen, über einen Button ein Ticket zu eröffnen, woraufhin eine „Sekretärin Sigrid“ (KI) direkt im Channel erste Fragen stellt und entscheidet, ob der/die Nutzer\*in kooperativ ist. Anschließend kann das Support-/Admin-Team das Ticket übernehmen, bearbeiten, schließen oder löschen.  

Zusätzlich enthält das Projekt eine Flask-Webanwendung (zugänglich über Discord-OAuth2-Login), die Übersichten und Transkripte der Tickets anzeigt.

---

## Inhaltsverzeichnis

1. [Funktionsübersicht](#funktionsübersicht)  
2. [Voraussetzungen](#voraussetzungen)  
3. [Discord Developer Portal: Bot erstellen & einrichten](#discord-developer-portal-bot-erstellen--einrichten)  
   1. [Neue Application erstellen](#neue-application-erstellen)  
   2. [Bot anlegen](#bot-anlegen)  
   3. [Privileged Gateway Intents](#privileged-gateway-intents)  
   4. [Bot einladen (Invite-Link)](#bot-einladen-invite-link)  
   5. [Slash Commands](#slash-commands)  
4. [Projektstruktur](#projektstruktur)  
5. [Installation & Konfiguration](#installation--konfiguration)  
6. [Start des Discord-Bots (lokal)](#start-des-discord-bots-lokal)  
7. [Start des Flask-Webservers (lokal)](#start-des-flask-webservers-lokal)  
8. [Produktivbetrieb](#produktivbetrieb)  
   1. [Gunicorn für Flask-Webapp](#gunicorn-für-flask-webapp)  
   2. [Systemd-Service für mainpy (Discord-Bot)](#systemd-service-für-mainpy-discord-bot)  
   3. [Systemd-Service für Gunicorn (Webapp)](#systemd-service-für-gunicorn-webapp)  
9. [Discord-Bot-Kommandos & Workflow](#discord-bot-kommandos--workflow)  
10. [Web-Panel: Funktionen](#web-panel-funktionen)  
11. [Lizenz / Hinweise](#lizenz--hinweise)

---

## Funktionsübersicht

- **Ticket-Erstellung** via Button in Discord-Kanälen.  
- **KI-Unterstützung**: Stellt anfangs Fragen (z. B. nach einer Bann-ID) und prüft Kooperationsbereitschaft.  
- **Manuelles Claiming**: Supporter/Admins können Tickets beanspruchen, schreiben und den User direkt betreuen.  
- **Abschluss**: Ticket schließen (Archiv in „Closed“-Kategorie, Transkript wird gespeichert) oder Ticket löschen (Kanal weg, Transkript bleibt in der Datenbank).  
- **Web-Panel** (Flask) mit Discord-OAuth2-Anmeldung, um Ticketlisten und Transkripte einzusehen.

---

## Voraussetzungen

- **Python 3.9** oder höher (empfohlen).  
- **Discord-Bot** (Client-ID, Bot-Token) – Anlegen und konfigurieren siehe unten.  
- **OpenAI-API-Key** (für GPT-3.5).  
- **SQLite** (in Python enthalten).  
- Python-Bibliotheken wie `discord.py`/`py-cord`, `openai`, `flask`, `requests`, `python-dotenv`, `aiohttp`.  
- (Optional) `gunicorn` für einen produktiven Betrieb der Flask-App.

---

## Discord Developer Portal: Bot erstellen & einrichten

### 1. Neue Application erstellen

1. Gehe zum [Discord Developer Portal](https://discord.com/developers/applications).  
2. Klicke auf **New Application**.  
3. Gib einen Namen für deine Anwendung ein, z. B. „TicketBot“.  
4. Klicke auf **Create**.

### 2. Bot anlegen

1. Wähle deine neue Anwendung aus.  
2. Gehe links auf **Bot**.  
3. Klicke auf **Add Bot** → **Yes, do it!**.  
4. Nun hast du einen **Bot-Account** innerhalb der Anwendung.  
5. Kopiere unter **TOKEN** deinen **Bot-Token** (dieser muss in deiner `.env` unter `BOT_TOKEN=` eingetragen werden!).  
6. (Optional) Passe das **Bot-Icon** und den **Benutzernamen** an.

### 3. Privileged Gateway Intents

1. In der Bot-Seite (im Developer Portal) scrolle zu **Privileged Gateway Intents**.  
2. Aktiviere ggf. **Message Content Intent**, wenn du benötigst, dass dein Bot Nachrichteninhalte lesen kann (hier im Code ist `message_content = True` gesetzt, also wird das benötigt).  
3. Aktiviere ggf. auch **Presence Intent** oder **Server Members Intent** falls du das brauchst (hier ggf. nur `members` relevant).  
4. Klicke auf **Save Changes**.

### 4. Bot einladen (Invite-Link)

1. Gehe links auf **OAuth2 > URL Generator**.  
2. Wähle unter **Scopes**: `bot` & `applications.commands` (für Slash-Befehle).  
3. Unter **Bot Permissions** wähle die nötigen Rechte (z. B. `Send Messages`, `Manage Channels`, `Manage Roles` – je nachdem, welche Aktionen dein Bot ausführen muss, insb. um Tickets zu erstellen oder Rechte zu setzen).  
4. Der generierte Link (unten) kann jetzt kopiert und im Browser aufgerufen werden.  
5. Wähle den Server, auf dem der Bot hinzugefügt werden soll, und bestätige.  

Anschließend ist der Bot auf deinem Server. Stelle sicher, dass er die Rechte hat, die er braucht (z. B. um Channels zu erstellen).

### 5. Slash Commands

- Standardmäßig registriert Discord Slash-Befehle automatisch, wenn du sie in deinem Code (z. B. in `ticket_cog.py` oder `transcript_cog.py`) definiert hast.  
- Stelle sicher, dass in den Bot-Einstellungen unter **General Information** das Feld **Public Bot** (ggf. an) und die Intents korrekt gesetzt sind, damit Slash Commands ordnungsgemäß ankommen.  
- Manchmal kann es mehrere Minuten dauern, bis neue Slash Commands im Server verfügbar sind.

---

## Projektstruktur

```bash
.
├── main.py                 # Startpunkt für den Discord-Bot
├── cogs/
│   ├── ticket_cog.py       # Hauptlogik (Ticketverwaltung + KI)
│   └── transcript_cog.py   # /ticket_transcript-Befehl
├── utils/
│   ├── config.py           # Lädt .env-Variablen, enthält IDs und Konstanten
│   └── database.py         # SQLite-Datenbankzugriff
├── webapp/
│   ├── app.py              # Flask-Anwendung (Web-Panel)
│   ├── templates/
│   │   ├── index.html      # Übersicht aller Tickets
│   │   └── transcript_detail.html  # Zeigt ein einzelnes Transkript
│   └── static/             # (optionale statische Dateien)
├── tickets.sqlite          # SQLite-Datenbank (wird automatisch angelegt)
├── .env                    # Deine Umgebungsvariablen
└── requirements.txt        # Liste benötigter Pakete (Beispiel)
```

---

## Installation & Konfiguration

1. **Projekt klonen/entpacken**  
   Lade das Projekt in einen geeigneten Ordner.

2. **Virtuelle Umgebung (optional, empfohlen)**  
   ```bash
   python -m venv venv
   source venv/bin/activate  # (Linux/Mac)
   # Windows: venv\Scripts\activate
   ```

3. **Abhängigkeiten installieren**  
   ```bash
   pip install -r requirements.txt
   ```
   Wenn keine `requirements.txt` vorliegt, erstelle eine mit ähnlichem Inhalt:
   ```
   discord.py==2.1.0
   openai==0.27.0
   flask==2.3.2
   requests==2.31.0
   python-dotenv==1.0.0
   aiohttp==3.8.4
   gunicorn==20.1.0   # nur falls benötigt
   ```

4. **Konfiguration in `.env`**  
   Erstelle eine Datei namens `.env` (im Hauptverzeichnis). Beispiel:
   ```env
   BOT_TOKEN=DEIN_DISCORD_BOT_TOKEN
   GUILD_ID=123456789123456789

   SUPPORT_ROLE_ID=111111111111111111
   ADMIN_ROLE_ID=222222222222222222
   VIEWER_ROLE_ID=333333333333333333
   VIEWER2_ROLE_ID=444444444444444444

   CREATED_TICKETS_CATEGORY_ID=555555555555555555
   CLAIMED_TICKETS_CATEGORY_ID=666666666666666666
   CLOSED_TICKETS_CATEGORY_ID=777777777777777777

   TICKET_LOG_CHANNEL_ID=888888888888888888
   MAX_TICKETS_PER_SUPPORTER=3
   TICKET_CLEANUP_DAYS=7

   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-3.5-turbo

   # Flask WebApp
   FLASK_SECRET_KEY=EinLangerGeheimerString
   DISCORD_CLIENT_ID=1234567890
   DISCORD_CLIENT_SECRET=ABCDEFGHIJKLMNOPQRST
   DISCORD_REDIRECT_URI=https://deine-app.de/callback
   ```
   **Wichtig**:
   - Trage deinen eigenen Bot-Token (`BOT_TOKEN`) aus dem Developer Portal ein.  
   - Die IDs (`GUILD_ID`, `SUPPORT_ROLE_ID` usw.) müssen deinen Server/Rollen widerspiegeln.  
   - `OPENAI_API_KEY` ist dein Key für die GPT-3.5-API.  
   - Die Discord OAuth2-Daten (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`) sind für die Web-App-Anmeldung relevant.

---

## Start des Discord-Bots (lokal)

1. Terminal öffnen, ins Projektverzeichnis wechseln.  
2. (Optional) Virtuelle Umgebung aktivieren.  
3. **Bot starten**:
   ```bash
   python main.py
   ```
4. Auf der Konsole sollten Meldungen wie  
   ```
   [LOG] Erfolgreich cogs.ticket_cog geladen.
   [LOG] Erfolgreich cogs.transcript_cog geladen.
   [LOG] Starte Bot...
   [LOG] Eingeloggt als DeinBotName (ID: 123456789)
   ```
   erscheinen. Der Bot ist nun auf deinem Server online (sofern Token & IDs stimmen).

---

## Start des Flask-Webservers (lokal)

1. Prüfe `.env`: **`FLASK_SECRET_KEY`**, **`DISCORD_CLIENT_ID`**, **`DISCORD_CLIENT_SECRET`**, **`DISCORD_REDIRECT_URI`**.  
2. Starte die Flask-App:
   ```bash
   python webapp/app.py
   ```
3. Sie läuft in der Voreinstellung auf `http://127.0.0.1:60123`.  
4. Öffne die URL im Browser. Du wirst über Discord-OAuth2 geleitet (sofern `DISCORD_REDIRECT_URI` korrekt eingetragen ist).

---

## Produktivbetrieb

Im produktiven Umfeld empfiehlt es sich, den Discord-Bot (`main.py`) als **Systemd-Service** laufen zu lassen und die Flask-App mit **Gunicorn** (ebenfalls in einem Systemd-Service) zu betreiben. So kannst du beide Prozesse dauerhaft und stabil im Hintergrund laufen lassen und über einen Reverse Proxy (Nginx/Apache) absichern.

### Gunicorn für Flask-Webapp

1. **Gunicorn installieren** (falls nicht bereits geschehen):
   ```bash
   pip install gunicorn
   ```
2. **Gunicorn starten** (Beispiel):
   ```bash
   gunicorn -w 2 -b 0.0.0.0:60123 webapp.app:app
   ```
   - `-w 2` = 2 Worker-Prozesse.  
   - `-b 0.0.0.0:60123` = Port 60123 auf allen Interfaces.  
   - `webapp.app:app` = Importiere das Flask-App-Objekt `app` aus `webapp/app.py`.

### Systemd-Service für main.py (Discord-Bot)

Lege eine Service-Datei an, z. B. `/etc/systemd/system/discord_ticketbot.service`:

```ini
[Unit]
Description=Discord Ticketbot
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/pfad/zu/deinem/projekt
ExecStart=/pfad/zu/deinem/projekt/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Anschließend**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable discord_ticketbot
sudo systemctl start discord_ticketbot
sudo systemctl status discord_ticketbot
```

### Systemd-Service für Gunicorn (Webapp)

Lege eine zweite Service-Datei an, z. B. `/etc/systemd/system/ticketweb_gunicorn.service`:

```ini
[Unit]
Description=Gunicorn for Ticket WebApp
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/pfad/zu/deinem/projekt
ExecStart=/pfad/zu/deinem/projekt/venv/bin/gunicorn --workers 2 --bind 0.0.0.0:60123 webapp.app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Dann:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ticketweb_gunicorn
sudo systemctl start ticketweb_gunicorn
sudo systemctl status ticketweb_gunicorn
```

### Reverse Proxy (z. B. NGINX)

In der Regel leitest du in der produktiven Umgebung den Traffic per HTTPS von NGINX/Apache zu Gunicorn weiter. Ein Beispiel (NGINX, HTTP → Proxy → Gunicorn auf Port 60123):

```nginx
server {
    listen 80;
    server_name deine-app.de;

    location / {
        proxy_pass http://127.0.0.1:60123;
        proxy_http_version 1.1;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Host $host;
    }
}
```

Anschließend kannst du Let's Encrypt oder ein anderes SSL-Zertifikat aktivieren.

---

## Discord-Bot-Kommandos & Workflow

1. **Slash-Befehl: `/setup_ticket_button`**  
   - Nur für Admin-Rolle (`ADMIN_ROLE_ID`).  
   - Erstellt eine Nachricht mit „Ticket erstellen“-Button im aktuellen Channel.

2. **Ticket-Kanal**  
   - Klick → Neuer Textkanal in Kategorie `CREATED_TICKETS_CATEGORY_ID`.  
   - KI (Sekretärin Sigrid) begrüßt, fragt nach ID und klärt den Banngrund.  

3. **Ticket beanspruchen**  
   - Button: „Ticket beanspruchen“ → Wechselt in `CLAIMED_TICKETS_CATEGORY_ID`.  

4. **Ticket schließen**  
   - Button: „Ticket schließen“ → Kanal wird archiviert in `CLOSED_TICKETS_CATEGORY_ID`, Transkript gespeichert, KI wird beendet.  

5. **Ticket löschen**  
   - Button: „Ticket löschen“ → Kanal wird gelöscht, Transkript bleibt in der Datenbank.  

6. **`/ticket_transcript`**  
   - Erstellt / aktualisiert Transkript manuell (nur Supporter/Admin).

---

## Web-Panel: Funktionen

- **Übersichtsseite (`/`)**: Zeigt alle Tickets (ID, Ersteller, Status, neuestes Transkript).  
- **Transkriptansicht**: Zeigt den Chatverlauf eines Tickets.  
- **Login** über Discord-OAuth2; nur Rollen aus `ALLOWED_ROLES` (siehe `.env`) haben Zugriff.

---

## Lizenz / Hinweise

- Dieses Projekt nutzt Abhängigkeiten mit eigenen Lizenzen (Discord, OpenAI, Flask etc.). Prüfe deren Bestimmungen.  
- Achte auf die **Nutzungsrichtlinien** von Discord und OpenAI.  
- Du kannst den Code an deine eigenen Bedürfnisse anpassen.

---

**Viel Erfolg mit deinem Ticket-Bot!**  
Bei Fragen oder Problemen kannst du etwa Issues in deinem Versionskontrollsystem anlegen oder das Support-Team kontaktieren.