import discord
from discord.ext import commands

from utils import config
from utils.database import Database

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Unsere Cogs
initial_cogs = [
    "cogs.ticket_cog",
    "cogs.transcript_cog"
]

@bot.event
async def on_ready():
    """
    Wird aufgerufen, sobald der Bot eingeloggt ist.
    1) Korrigiert automatisch die Kategorie-Permissions
    2) Registriert Slash-Befehle (sync)
    3) Stellt ggf. den Ticket-Button wieder her
    4) Stellt ggf. die Admin-Buttons in offenen Tickets wieder her
    """
    print(f"[LOG] Eingeloggt als {bot.user} (ID: {bot.user.id})")

    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        print(f"[Warnung] Konnte Guild mit ID {config.GUILD_ID} nicht finden.")
        return

    # Kategorien laden
    created_cat = guild.get_channel(config.CREATED_TICKETS_CATEGORY_ID)
    claimed_cat = guild.get_channel(config.CLAIMED_TICKETS_CATEGORY_ID)
    closed_cat = guild.get_channel(config.CLOSED_TICKETS_CATEGORY_ID)

    # Rollen
    everyone = guild.default_role
    support_role = guild.get_role(config.SUPPORT_ROLE_ID)
    admin_role = guild.get_role(config.ADMIN_ROLE_ID)
    viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
    viewer_role2 = guild.get_role(config.VIEWER2_ROLE_ID)

    # 1) Kategorie-Permissions anpassen
    if created_cat:
        await fix_category_perms(
            category=created_cat,
            everyone_view=False, everyone_send=False,
            support_view=True, support_send=True,
            admin_view=True, admin_send=True,
            viewer_view=True, viewer_send=False,
            support_role=support_role,
            admin_role=admin_role,
            viewer_role=viewer_role,
            viewer_role2=viewer_role2,
            everyone=everyone
        )
    if claimed_cat:
        await fix_category_perms(
            category=claimed_cat,
            everyone_view=False, everyone_send=False,
            support_view=True, support_send=True,
            admin_view=True, admin_send=True,
            viewer_view=True, viewer_send=False,
            support_role=support_role,
            admin_role=admin_role,
            viewer_role=viewer_role,
            viewer_role2=viewer_role2,
            everyone=everyone
        )
    if closed_cat:
        await fix_category_perms(
            category=closed_cat,
            everyone_view=False, everyone_send=False,
            support_view=True, support_send=False,
            admin_view=True, admin_send=False,
            viewer_view=True, viewer_send=False,
            support_role=support_role,
            admin_role=admin_role,
            viewer_role=viewer_role,
            viewer_role2=viewer_role2,
            everyone=everyone
        )

    print("[LOG] Automatisches Setzen der Kategorie-Berechtigungen abgeschlossen.")

    # 2) Slash-Befehle registrieren (sync)
    try:
        synced = await bot.sync_commands()
        if synced is None:
            print("[LOG] Slash-Befehle wurden erfolgreich synchronisiert (sync_commands() => None).")
            print("[LOG] Registrierte Slash-Befehle:")
            for cmd in bot.application_commands:
                print(f"   - /{cmd.name}")
        else:
            print(f"[LOG] {len(synced)} Slash-Befehle wurden erfolgreich registriert:")
            for cmd in synced:
                print(f"   - /{cmd.name}")
    except Exception as e:
        print(f"[ERROR] Fehler beim Syncen der Slash-Befehle: {e}")

    # 3) Falls wir schon eine Ticket-Button-Nachricht in der DB haben, View erneut dranheften
    db = Database()
    channel_id = db.get_bot_setting("TICKET_BUTTON_CHANNEL_ID")
    message_id = db.get_bot_setting("TICKET_BUTTON_MESSAGE_ID")

    if channel_id and message_id:
        try:
            channel_id = int(channel_id)
            message_id = int(message_id)
            channel = guild.get_channel(channel_id)

            if channel:
                # Alte Nachricht per ID holen
                old_msg = await channel.fetch_message(message_id)
                # Cog + View-Klasse importieren
                from cogs.ticket_cog import TicketCog, CreateTicketView
                ticket_cog = bot.get_cog("TicketCog")

                if ticket_cog and old_msg:
                    # Neue View an alte Nachricht anheften
                    new_view = CreateTicketView(ticket_cog)
                    await old_msg.edit(view=new_view)
                    print(f"[LOG] Ticket-Button (Message-ID={message_id}) wurde erfolgreich erneut aktiviert.")
                else:
                    print("[WARN] Konnte den TicketCog oder die alte Nachricht nicht finden.")
            else:
                print("[WARN] Konnte den Ticket-Button-Channel nicht finden.")
        except Exception as e:
            print(f"[WARN] Fehler beim Wiederherstellen der Ticket-Button-Message: {e}")
    else:
        print("[LOG] Keine gespeicherte Ticket-Button-Message gefunden. /setup_ticket_button ggf. ausführen.")

    # 4) Admin-Buttons bei offenen Tickets wiederherstellen
    try:
        open_tickets = db.get_open_or_claimed_tickets()
        if not open_tickets:
            print("[LOG] Keine offenen/claimed Tickets zu aktualisieren.")
        else:
            from cogs.ticket_cog import TicketCog, TicketAdminView
            ticket_cog = bot.get_cog("TicketCog")

            if not ticket_cog:
                print("[WARN] Konnte TicketCog nicht finden, Admin-Buttons können nicht wiederhergestellt werden.")
            else:
                for t in open_tickets:
                    chan_id = t["channel_id"]
                    admin_msg_id = t["admin_message_id"]
                    tid = t["ticket_id"]

                    if not admin_msg_id:
                        # Falls wir für dieses Ticket noch keine admin_message_id gespeichert haben, überspringen wir
                        continue

                    ticket_channel = guild.get_channel(int(chan_id))
                    if not ticket_channel:
                        print(f"[WARN] Ticket-Channel {chan_id} nicht gefunden (Ticket #{tid}).")
                        continue

                    try:
                        old_admin_msg = await ticket_channel.fetch_message(int(admin_msg_id))
                        if old_admin_msg:
                            admin_view = TicketAdminView(ticket_cog)
                            await old_admin_msg.edit(view=admin_view)
                            print(f"[LOG] Admin-View für Ticket #{tid} wiederhergestellt (Nachricht {admin_msg_id}).")
                    except Exception as e:
                        print(f"[WARN] Konnte Admin-Buttons in Ticket #{tid} nicht wiederherstellen: {e}")
    except Exception as e:
        print(f"[WARN] Fehler beim Wiederherstellen der Admin-Buttons: {e}")

    print("------")


async def fix_category_perms(
    category: discord.CategoryChannel,
    everyone_view: bool, everyone_send: bool,
    support_view: bool, support_send: bool,
    admin_view: bool, admin_send: bool,
    viewer_view: bool, viewer_send: bool,
    support_role: discord.Role, admin_role: discord.Role,
    viewer_role: discord.Role, viewer_role2: discord.Role,
    everyone: discord.Role
):
    """
    Setzt Standard-Permissions für eine Kategorie.
    """
    # Jeder (everyone) darf nix
    await category.set_permissions(everyone, view_channel=everyone_view, send_messages=everyone_send)

    # Support
    if support_role:
        await category.set_permissions(support_role, view_channel=support_view, send_messages=support_send)

    # Admin
    if admin_role:
        await category.set_permissions(admin_role, view_channel=admin_view, send_messages=admin_send)

    # Viewer 1
    if viewer_role:
        await category.set_permissions(viewer_role, view_channel=viewer_view, send_messages=viewer_send)

    # Viewer 2
    if viewer_role2:
        await category.set_permissions(viewer_role2, view_channel=viewer_view, send_messages=viewer_send)


def main():
    # Cogs laden
    for cog in initial_cogs:
        try:
            bot.load_extension(cog)
            print(f"[LOG] Erfolgreich {cog} geladen.")
        except Exception as e:
            print(f"[ERROR] Fehler beim Laden von {cog}: {e}")

    print("[LOG] Starte Bot...")
    bot.run(config.BOT_TOKEN)


if __name__ == "__main__":
    main()
