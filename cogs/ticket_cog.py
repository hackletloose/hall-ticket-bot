import discord
from discord.ext import commands

from utils import config, database

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = database.Database()
        # Um gleichzeitige /create-Klicks zu verhindern
        self.creating_tickets_for = set()

    @commands.Cog.listener()
    async def on_ready(self):
        print("[TicketCog] bereit.")

    @commands.slash_command(
        name="setup_ticket_button",
        description="Erstellt im aktuellen Kanal eine Nachricht mit einem Ticket-Button (nur Admin)."
    )
    @commands.has_role(config.ADMIN_ROLE_ID)
    async def setup_ticket_button(self, ctx: discord.ApplicationContext):
        """
        Legt einen Button an, den User zum Erstellen eines Tickets drücken können.
        Nur Admins können diesen Befehl ausführen.
        """
        embed = discord.Embed(
            title="Ticket-Hilfe",
            description="Klicke auf den Button, um ein neues Ticket zu erstellen. Bitte gib uns Informationen über deinen Bann. Nenne uns auch deinen Spielernamen und deine zugehörige ID.",
            color=discord.Color.green()
        )

        create_btn = discord.ui.Button(
            label="Ticket erstellen",
            style=discord.ButtonStyle.danger,
            custom_id="create_ticket_button"
        )
        view = discord.ui.View()
        view.add_item(create_btn)

        await ctx.channel.send(embed=embed, view=view)
        await ctx.respond("Ticket-Button wurde platziert.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """
        Reagiert auf Button-Klicks (component-Interactions).
        """
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id", "")
            if custom_id == "create_ticket_button":
                await self.create_ticket(interaction)
            elif custom_id.startswith("claim_ticket_"):
                await self.claim_ticket(interaction)
            elif custom_id.startswith("close_ticket_"):
                await self.close_ticket(interaction)
            elif custom_id.startswith("delete_ticket_"):
                await self.delete_ticket(interaction)

    async def create_ticket(self, interaction: discord.Interaction):
        """
        Erstellt ein neues Ticket (Textchannel). Viewer-Rolle hat hier direkt Leserechte, 
        aber keine Schreibrechte.
        """
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        guild = interaction.guild

        # Schutz vor Spamming
        if user.id in self.creating_tickets_for:
            await interaction.followup.send(
                "Du erstellst gerade bereits ein Ticket. Bitte warte einen Augenblick.",
                ephemeral=True
            )
            return

        self.creating_tickets_for.add(user.id)
        try:
            ticket_id = self.db.get_next_ticket_id()

            category = guild.get_channel(config.CREATED_TICKETS_CATEGORY_ID)
            if not category:
                await interaction.followup.send(
                    "Fehler: Ticket-Kategorie nicht gefunden.",
                    ephemeral=True
                )
                return

            # Kanalname: <ErstellerName>-<TicketID>
            creator_name = user.name.replace(" ", "-")[:20]
            channel_name = f"{creator_name}-{ticket_id}"

            # Ticket-Kanal erstellen
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                reason=f"Ticket #{ticket_id} erstellt"
            )
            await ticket_channel.edit(sync_permissions=True)

            # Ersteller: lesen+schreiben
            await ticket_channel.set_permissions(user, view_channel=True, send_messages=True)

            # Viewer-Rolle darf nur lesen, nicht schreiben
            viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
            if viewer_role:
                await ticket_channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

            self.db.log_ticket_created(ticket_id, user.id, ticket_channel.id)

            # Embed + Buttons
            embed = discord.Embed(
                title=f"Ticket #{ticket_id}",
                description=(
                    f"Willkommen {user.mention}! Ein Supporter wird sich gleich um dich kümmern.\n\n"
                    "Bitte gib uns Informationen über deinen Bann. Nenne uns auch deinen Spielernamen und deine zugehörige ID."
                ),
                color=discord.Color.blue()
            )

            claim_btn = discord.ui.Button(
                label="Ticket beanspruchen",
                style=discord.ButtonStyle.success,
                custom_id=f"claim_ticket_{ticket_id}"
            )
            close_btn = discord.ui.Button(
                label="Ticket schließen",
                style=discord.ButtonStyle.danger,
                custom_id=f"close_ticket_{ticket_id}"
            )
            delete_btn = discord.ui.Button(
                label="Ticket löschen",
                style=discord.ButtonStyle.danger,
                custom_id=f"delete_ticket_{ticket_id}"
            )

            view = discord.ui.View()
            view.add_item(claim_btn)
            view.add_item(close_btn)
            view.add_item(delete_btn)

            await ticket_channel.send(
                content=user.mention,
                embed=embed,
                view=view
            )

            await interaction.followup.send(
                f"Ticket erstellt: {ticket_channel.mention}",
                ephemeral=True
            )

        finally:
            self.creating_tickets_for.discard(user.id)

    async def claim_ticket(self, interaction: discord.Interaction):
        """
        Wenn ein Ticket geclaimed wird, verschieben wir es in die Claimed-Kategorie,
        nehmen ggf. anderen Supportern das Schreibrecht, und gewähren dem Claimer Schreibrecht.
        Die Viewer-Rolle behält Leserechte.
        """
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message(
                "Du bist kein Supporter/Admin und darfst das nicht!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        channel = interaction.channel
        parts = channel.name.split("-")
        if len(parts) < 2:
            await interaction.followup.send(
                "Dies scheint kein gültiger Ticket-Kanal zu sein.",
                ephemeral=True
            )
            return

        # Ticket-ID ist das letzte Element
        try:
            ticket_id = int(parts[-1])
        except ValueError:
            await interaction.followup.send("Konnte Ticket-ID nicht bestimmen.", ephemeral=True)
            return

        # Verschieben in "Claimed"
        claimed_cat = interaction.guild.get_channel(config.CLAIMED_TICKETS_CATEGORY_ID)
        if claimed_cat:
            await channel.edit(category=claimed_cat, sync_permissions=True)

        # Supportern das Schreiben entziehen
        guild = interaction.guild
        support_role = guild.get_role(config.SUPPORT_ROLE_ID)
        if support_role:
            await channel.set_permissions(support_role, send_messages=False)

        # Claimer darf schreiben
        await channel.set_permissions(interaction.user, view_channel=True, send_messages=True)

        # Ersteller: nicht aussperren
        ticket_user_id = self.db.get_ticket_user(ticket_id)
        if ticket_user_id:
            ticket_user = guild.get_member(ticket_user_id)
            if ticket_user:
                await channel.set_permissions(ticket_user, view_channel=True, send_messages=True)

        # Viewer-Rolle: nur lesen
        viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
        if viewer_role:
            await channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

        self.db.log_ticket_claimed(ticket_id, interaction.user.id)

        # Kanalname: <ErstellerName>-<ClaimerName>-<TicketID>
        # (ErstellerName war alles außer letztes Element, Claimer = interaction.user)
        creator_name = "-".join(parts[:-1])
        claimer_name = interaction.user.name.replace(" ", "-")[:20]
        new_name = f"{creator_name}-{claimer_name}-{ticket_id}"
        await channel.edit(name=new_name)

        await interaction.followup.send(
            f"Ticket #{ticket_id} wurde von {interaction.user.mention} beansprucht.",
            ephemeral=False
        )

    async def close_ticket(self, interaction: discord.Interaction):
        """
        Ticket schließen: Nur Support/Admin darf. Viewer behält Leserechte, 
        bis wir es in die Closed-Kategorie verschieben.
        """
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message(
                "Du bist kein Supporter/Admin und darfst das nicht!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        channel = interaction.channel
        parts = channel.name.split("-")
        if len(parts) < 2:
            await interaction.followup.send(
                "Dies scheint kein gültiger Ticket-Kanal zu sein.",
                ephemeral=True
            )
            return

        try:
            ticket_id = int(parts[-1])
        except ValueError:
            await interaction.followup.send("Konnte Ticket-ID nicht bestimmen.", ephemeral=True)
            return

        self.db.log_ticket_closed(ticket_id)

        await channel.send("Ticket wird geschlossen. Bitte hier nichts mehr schreiben.")

        # Transkript
        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
        transcript_text = "\n".join(lines)
        self.db.save_transcript(ticket_id, transcript_text)
        await channel.send("Transkript wurde automatisch erstellt und gespeichert.")

        # In "Closed"-Kategorie
        closed_cat = interaction.guild.get_channel(config.CLOSED_TICKETS_CATEGORY_ID)
        if closed_cat:
            await channel.edit(category=closed_cat, sync_permissions=True)

        # Viewer-Rolle soll auch in Closed noch lesen können? => wir können es erneut setzen
        viewer_role = interaction.guild.get_role(config.VIEWER_ROLE_ID)
        if viewer_role:
            await channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

        await channel.send("Ticket ist nun geschlossen.")
        await interaction.followup.send(
            f"Ticket #{ticket_id} wurde geschlossen.",
            ephemeral=True
        )

    async def delete_ticket(self, interaction: discord.Interaction):
        """
        Ticket löschen: nur Support/Admin.
        Viewer-Rolle hat keinen Einfluss mehr - Kanal wird gelöscht.
        """
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message(
                "Du bist kein Supporter/Admin und darfst das nicht!",
                ephemeral=True
            )
            return
        await interaction.response.defer()

        channel = interaction.channel
        parts = channel.name.split("-")
        if len(parts) < 2:
            await interaction.followup.send("Dies scheint kein gültiger Ticket-Kanal zu sein.", ephemeral=True)
            return
        try:
            ticket_id = int(parts[-1])
        except ValueError:
            await interaction.followup.send("Konnte Ticket-ID nicht bestimmen.", ephemeral=True)
            return

        # Letztes Transkript
        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
        transcript_text = "\n".join(lines)
        self.db.save_transcript(ticket_id, transcript_text)

        self.db.log_ticket_deleted(ticket_id)
        await channel.send("Ticket-Kanal wird gelöscht...")
        await channel.delete()

        await interaction.followup.send(
            f"Ticket #{ticket_id} wurde gelöscht (Transkript bleibt gespeichert).",
            ephemeral=True
        )

    ########################################################################
    # Hilfsfunktion: Prüft, ob User Support/Admin
    ########################################################################
    def has_support_role(self, member: discord.Member):
        return any(r.id == config.SUPPORT_ROLE_ID for r in member.roles) \
            or any(r.id == config.ADMIN_ROLE_ID for r in member.roles)

def setup(bot):
    bot.add_cog(TicketCog(bot))
