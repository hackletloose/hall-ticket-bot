# cogs/transcript_cog.py
import discord
from discord.ext import commands

from utils import config, database

class TranscriptCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = database.Database()

    @commands.slash_command(
        name="ticket_transcript",
        description="Erzeugt ein Transkript des aktuellen Tickets."
    )
    @commands.has_any_role(config.SUPPORT_ROLE_ID, config.ADMIN_ROLE_ID)
    async def ticket_transcript(self, ctx: discord.ApplicationContext):
        channel = ctx.channel
        if not channel.name.startswith("ticket-"):
            await ctx.respond("Dies ist kein Ticket-Kanal.", ephemeral=True)
            return

        ticket_id = channel.name.replace("ticket-", "")
        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]

        transcript_lines = []
        for msg in messages:
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            transcript_lines.append(f"[{timestamp}] {msg.author.display_name}: {msg.content}")

        transcript_text = "\n".join(transcript_lines)
        self.db.save_transcript(ticket_id, transcript_text)

        await ctx.respond(f"Transkript für Ticket #{ticket_id} wurde erstellt und gespeichert.")

def setup(bot):
    bot.add_cog(TranscriptCog(bot))

