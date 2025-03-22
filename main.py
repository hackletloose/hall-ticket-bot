import discord
from discord.ext import commands

from utils import config

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

initial_cogs = [
    "cogs.ticket_cog",
    "cogs.transcript_cog"
]

@bot.event
async def on_ready():
    """
    Wird aufgerufen, sobald der Bot eingeloggt ist.
    Wir setzen hier beim Start automatisch die Kategorie-Berechtigungen
    für unsere Ticket-Kategorien.
    """
    print(f"[LOG] Eingeloggt als {bot.user} (ID: {bot.user.id})")

    guild = bot.get_guild(config.GUILD_ID)
    if guild is None:
        print(f"[Warnung] Guild mit ID {config.GUILD_ID} nicht gefunden.")
        return

    created_cat = guild.get_channel(config.CREATED_TICKETS_CATEGORY_ID)
    claimed_cat = guild.get_channel(config.CLAIMED_TICKETS_CATEGORY_ID)
    closed_cat = guild.get_channel(config.CLOSED_TICKETS_CATEGORY_ID)

    if not created_cat:
        print("[Warnung] CREATED_TICKETS_CATEGORY_ID nicht gefunden.")
    if not claimed_cat:
        print("[Warnung] CLAIMED_TICKETS_CATEGORY_ID nicht gefunden.")
    if not closed_cat:
        print("[Warnung] CLOSED_TICKETS_CATEGORY_ID nicht gefunden.")

    # Rollen
    everyone = guild.default_role
    support_role = guild.get_role(config.SUPPORT_ROLE_ID)
    admin_role = guild.get_role(config.ADMIN_ROLE_ID)
    viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
    viewer_role2 = guild.get_role(config.VIEWER2_ROLE_ID)  # NEU

    # Overwrites (Created)
    await fix_category_perms(
        category=created_cat,
        everyone_view=False, everyone_send=False,
        support_view=True, support_send=True,
        admin_view=True, admin_send=True,
        viewer_view=True, viewer_send=False,
        support_role=support_role,
        admin_role=admin_role,
        viewer_role=viewer_role,
        viewer_role2=viewer_role2,  # NEU
        everyone=everyone
    )

    # Overwrites (Claimed)
    await fix_category_perms(
        category=claimed_cat,
        everyone_view=False, everyone_send=False,
        support_view=True, support_send=True,
        admin_view=True, admin_send=True,
        viewer_view=True, viewer_send=False,
        support_role=support_role,
        admin_role=admin_role,
        viewer_role=viewer_role,
        viewer_role2=viewer_role2,  # NEU
        everyone=everyone
    )

    # Overwrites (Closed)
    await fix_category_perms(
        category=closed_cat,
        everyone_view=False, everyone_send=False,
        support_view=True, support_send=False,
        admin_view=True, admin_send=False,
        viewer_view=True, viewer_send=False,
        support_role=support_role,
        admin_role=admin_role,
        viewer_role=viewer_role,
        viewer_role2=viewer_role2,  # NEU
        everyone=everyone
    )

    print("[LOG] Automatisches Setzen der Kategorie-Berechtigungen abgeschlossen.")
    print("------")

async def fix_category_perms(
    category: discord.CategoryChannel,
    everyone_view: bool, everyone_send: bool,
    support_view: bool, support_send: bool,
    admin_view: bool, admin_send: bool,
    viewer_view: bool, viewer_send: bool,
    support_role: discord.Role, admin_role: discord.Role,
    viewer_role: discord.Role, viewer_role2: discord.Role,  # NEU
    everyone: discord.Role
):
    """
    Setzt Standard-Permissions für eine Kategorie.
    Falls category=None, wird nichts unternommen.
    """
    if not category:
        return

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

    # Viewer 2 (NEU)
    if viewer_role2:
        await category.set_permissions(viewer_role2, view_channel=viewer_view, send_messages=viewer_send)

def main():
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
