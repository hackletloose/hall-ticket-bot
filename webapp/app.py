# webapp/app.py

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, g, session
)
import sqlite3
import os
import requests

from utils import config

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "..", "tickets.sqlite")

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def is_logged_in():
    """
    Prüft, ob der User eingeloggt ist (session["discord_id"]) und 'roles_ok' True ist.
    """
    return session.get("discord_id") and session.get("roles_ok")

def login_required(f):
    """
    Decorator: Leitet auf /login um, wenn der User nicht eingeloggt oder nicht berechtigt ist.
    """
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__  # Fix für Flask-Decorator
    return wrapper

@app.route("/login")
def login():
    """
    Leitet zur Discord OAuth2-Seite (Permissions: identify, guilds.members.read).
    """
    scope = "identify%20guilds.members.read"
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={config.DISCORD_CLIENT_ID}"
        f"&redirect_uri={config.DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
    )
    return redirect(url)

@app.route("/callback")
def callback():
    """
    Discord ruft diese URL nach erfolgreichem Login auf.
    Wir tauschen code gegen Token und checken Rollen in config.GUILD_ID.
    """
    code = request.args.get("code")
    if not code:
        flash("Discord-Login abgebrochen (kein code).")
        return redirect(url_for("login"))

    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "scope": "identify guilds.members.read"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_res = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    if token_res.status_code != 200:
        flash("Fehler beim Tokenabruf.")
        return redirect(url_for("login"))

    token_json = token_res.json()
    access_token = token_json["access_token"]
    token_type = token_json["token_type"]  # "Bearer"

    user_res = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"{token_type} {access_token}"}
    )
    if user_res.status_code != 200:
        flash("Fehler beim Abruf der Nutzerinformationen.")
        return redirect(url_for("login"))

    user_data = user_res.json()
    user_id = user_data["id"]

    guild_id = config.GUILD_ID
    member_url = f"https://discord.com/api/users/@me/guilds/{guild_id}/member"
    member_res = requests.get(member_url, headers={"Authorization": f"{token_type} {access_token}"})

    if member_res.status_code != 200:
        flash("Du bist nicht auf dem Discord-Server oder keine Berechtigung.")
        return redirect(url_for("login"))

    member_data = member_res.json()
    user_roles = member_data.get("roles", [])

    roles_ok = any(r in user_roles for r in config.ALLOWED_ROLES)
    if not roles_ok:
        flash("Du hast keine der erforderlichen Rollen. Zugriff verweigert.")
        return redirect(url_for("login"))

    session["discord_id"] = user_id
    session["roles_ok"] = True
    flash("Erfolgreich eingeloggt.")
    return redirect(url_for("index"))

@app.route("/")
@login_required
def index():
    con = get_db()
    cur = con.cursor()
    # Neu: user_name (Index 2) wird mit ausgewählt
    cur.execute("""
        SELECT t.id, t.user_id, t.user_name, t.status, tr.created_at
        FROM tickets t
        JOIN transcripts tr ON t.id = tr.ticket_id
        GROUP BY t.id
        ORDER BY tr.created_at DESC
    """)
    rows = cur.fetchall()
    return render_template("index.html", tickets=rows)

@app.route("/transcript/<int:ticket_id>")
@login_required
def show_transcript(ticket_id):
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT transcript_content
        FROM transcripts
        WHERE ticket_id=?
        ORDER BY transcript_id DESC
        LIMIT 1
    """, (ticket_id,))
    row = cur.fetchone()
    if not row:
        flash(f"Kein Transkript für Ticket {ticket_id} gefunden.")
        return redirect(url_for("index"))

    transcript_content = row[0]
    return render_template("transcript_detail.html",
                           ticket_id=ticket_id,
                           transcript=transcript_content)

if __name__ == "__main__":
    # Nur für lokalen Test
    # In Produktion besser via Gunicorn/WSGI
    app.run(debug=True, host="0.0.0.0", port=60123)
