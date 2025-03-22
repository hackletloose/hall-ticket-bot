# cogs/ticket_cog.py
import discord
from discord.ext import commands
import re
import aiohttp
import asyncio
import openai
import unicodedata
from collections import defaultdict

from utils import config, database

def safe_truncate(text: str, max_chars: int) -> str:
    """
    Kürzt den Text auf max_chars Zeichen. Hängt '... (gekürzt)' an, wenn zu lang ist.
    """
    if len(text) > max_chars:
        return text[:max_chars] + "... (gekürzt)"
    return text

def normalize_id_string(text: str) -> str:
    """
    Entfernt unsichtbare oder Steuerzeichen (Unicode-Kategorie 'C'),
    damit Regex auf alphanumerischen IDs nicht scheitert.
    """
    cleaned = []
    for c in text:
        if not unicodedata.category(c).startswith('C'):
            cleaned.append(c)
    return "".join(cleaned)

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = database.Database()

        # Um parallele /create-Klicks zu verhindern
        self.creating_tickets_for = set()

        # KI pro Channel (an/aus)
        self.ai_enabled_for_channel = {}

        # Chat-Verlauf: channel_id -> [ {role, content}, ...]
        self.conversations = defaultdict(list)

        # Speichert pro Ticket-Channel, ob eine ID bereits genannt wurde
        # channel_id -> (bool has_id, str stored_id)
        self.channel_has_id = defaultdict(lambda: (False, ""))

        # Zähler für uneinsichtiges Verhalten: channel_id -> int
        self.uncooperative_count = defaultdict(int)

        # OpenAI Setup
        self.openai_client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        self.openai_model = config.OPENAI_MODEL or "gpt-3.5-turbo"
        self.openai_temp = 0.7
        self.openai_max_tokens = 1000

    @commands.Cog.listener()
    async def on_ready(self):
        print("[LOG] [TicketCog] Ticket-Cog ist bereit.")

    @commands.slash_command(
        name="setup_ticket_button",
        description="Erstellt im aktuellen Kanal eine Nachricht mit einem Ticket-Button (nur Admin)."
    )
    @commands.has_role(config.ADMIN_ROLE_ID)
    async def setup_ticket_button(self, ctx: discord.ApplicationContext):
        embed = discord.Embed(
            title="Ticket-Hilfe",
            description=(
                "Klicke auf den Button, um ein neues Ticket zu erstellen. "
                "Wenn du gebannt wurdest, nenne bitte deine ID, damit wir dir Auskunft geben können."
            ),
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
        print("[LOG] Ticket-Button wurde im Kanal platziert.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Verwaltet Button-Interactions."""
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
        """Erstellt ein Ticket und aktiviert die KI im Kanal."""
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        guild = interaction.guild

        if user.id in self.creating_tickets_for:
            await interaction.followup.send(
                "Du erstellst gerade bereits ein Ticket. Bitte warte einen Augenblick.",
                ephemeral=True
            )
            print(f"[LOG] {user.name} hat versucht, gleichzeitig mehrere Tickets zu erstellen.")
            return

        self.creating_tickets_for.add(user.id)
        try:
            ticket_id = self.db.get_next_ticket_id()
            category = guild.get_channel(config.CREATED_TICKETS_CATEGORY_ID)
            if not category:
                await interaction.followup.send("Fehler: Ticket-Kategorie nicht gefunden.", ephemeral=True)
                print("[ERROR] Created-Tickets-Kategorie nicht gefunden.")
                return

            channel_name = f"{user.name.replace(' ', '-')[:20]}-{ticket_id}"
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                reason=f"Ticket #{ticket_id} erstellt"
            )
            await ticket_channel.edit(sync_permissions=True)
            await ticket_channel.set_permissions(user, view_channel=True, send_messages=True)

            viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
            if viewer_role:
                await ticket_channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

            self.db.log_ticket_created(ticket_id, user.id, ticket_channel.id)

            # KI aktivieren
            self.ai_enabled_for_channel[ticket_channel.id] = True

            embed = discord.Embed(
                title=f"Ticket #{ticket_id}",
                description=(
                    f"Willkommen {user.mention}! Bitte schildere kurz dein Anliegen. "
                    "Wenn du gebannt wurdest, teile uns **unbedingt** deine ID mit, "
                    "damit wir den Banngrund prüfen können."
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

            await ticket_channel.send(content=user.mention, embed=embed, view=view)
            print(f"[LOG] Ticket #{ticket_id} erstellt von {user.name} (ID: {user.id}).")

            # Erste KI-Nachricht
            first_text = (
                "Hallo, ich bin Sekretärin Siegrid. "
                "Bitte teile mir zuerst deine **ID** mit, damit ich deinen Banngrund nachschauen kann."
            )
            self.conversations[ticket_channel.id].append({
                "role": "assistant",
                "content": first_text
            })
            await ticket_channel.send(first_text)

            await interaction.followup.send(f"Ticket erstellt: {ticket_channel.mention}", ephemeral=True)
        finally:
            self.creating_tickets_for.discard(user.id)

    async def claim_ticket(self, interaction: discord.Interaction):
        """Ticket beanspruchen -> KI bleibt an, Admin/Support darf schreiben."""
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            print(f"[LOG] {interaction.user.name} wollte ein Ticket claimen, hat aber keine Rechte.")
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

        claimed_cat = interaction.guild.get_channel(config.CLAIMED_TICKETS_CATEGORY_ID)
        if claimed_cat:
            await channel.edit(category=claimed_cat, sync_permissions=True)

        guild = interaction.guild
        support_role = guild.get_role(config.SUPPORT_ROLE_ID)
        if support_role:
            # Sperre die Schreibrechte zunächst für den gesamten Support-Rang
            await channel.set_permissions(support_role, send_messages=False)

        await channel.set_permissions(interaction.user, view_channel=True, send_messages=True)

        ticket_user_id = self.db.get_ticket_user(ticket_id)
        if ticket_user_id:
            ticket_user = guild.get_member(ticket_user_id)
            if ticket_user:
                await channel.set_permissions(ticket_user, view_channel=True, send_messages=True)

        viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
        if viewer_role:
            await channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

        self.db.log_ticket_claimed(ticket_id, interaction.user.id)
        creator_name = "-".join(parts[:-1])
        claimer_name = interaction.user.name.replace(" ", "-")[:20]
        new_name = f"{creator_name}-{claimer_name}-{ticket_id}"
        await channel.edit(name=new_name)

        await interaction.followup.send(f"Ticket #{ticket_id} wurde von {interaction.user.mention} beansprucht.", ephemeral=False)
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} beansprucht.")

    async def close_ticket(self, interaction: discord.Interaction):
        """Ticket schließen -> KI aus, Archiv in Closed-Kategorie."""
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            print(f"[LOG] {interaction.user.name} wollte Ticket schließen, hat aber keine Rechte.")
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

        closed_cat = interaction.guild.get_channel(config.CLOSED_TICKETS_CATEGORY_ID)
        if closed_cat:
            await channel.edit(category=closed_cat, sync_permissions=True)

        viewer_role = interaction.guild.get_role(config.VIEWER_ROLE_ID)
        if viewer_role:
            await channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

        # KI aus
        self.ai_enabled_for_channel[channel.id] = False
        await channel.send("Ticket ist nun geschlossen.")
        await interaction.followup.send(f"Ticket #{ticket_id} wurde geschlossen.", ephemeral=True)
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} geschlossen.")

    async def delete_ticket(self, interaction: discord.Interaction):
        """Ticket löschen -> KI aus, Kanal gelöscht."""
        if not self.has_support_role(interaction.user):
            await interaction.response.send_message("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            print(f"[LOG] {interaction.user.name} wollte Ticket löschen, hat aber keine Rechte.")
            return
        await interaction.response.defer(ephemeral=True)
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

        await interaction.followup.send(f"Ticket #{ticket_id} wird nun gelöscht (Transkript bleibt gespeichert).", ephemeral=True)
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

        # KI aus
        self.ai_enabled_for_channel[channel.id] = False
        await channel.delete()
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} gelöscht.")

    ########################################################################
    # on_message: Kooperativ vs. unkooperativ per KI-Klassifikation + Logs
    ########################################################################
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        channel_id = message.channel.id

        # Wenn ein Supporter/Admin schreibt -> KI aus
        if self.has_support_role(message.author):
            if self.ai_enabled_for_channel.get(channel_id, False):
                self.ai_enabled_for_channel[channel_id] = False
                await message.channel.send(
                    "Ein Supporter oder Administrator ist jetzt anwesend. "
                    "Ich beende meine Antworten."
                )
                print(f"[LOG] KI im Channel {channel_id} deaktiviert, weil Support/Admin geschrieben hat.")
            return

        # Nur in Ticket-Kanälen reagieren
        if not self.is_ticket_channel(message.channel):
            return

        # KI aktiv?
        if not self.ai_enabled_for_channel.get(channel_id, False):
            return

        # Nachricht ins Konversations-Log
        user_text = normalize_id_string(message.content)
        self.conversations[channel_id].append({
            "role": "user",
            "content": user_text
        })
        print(f"[LOG] Neue Nachricht im Channel {channel_id} von {message.author.name}: {user_text}")

        # 1) Prüfe, ob Nutzer nach fertiger Entschuldigung fragt
        apology_keywords = [
            "entschuldigung schreiben", "formulieren", "apology", "help me write",
            "schreibe mir eine entschuldigung", "schreibe mir ein statement"
        ]
        if any(kw in user_text.lower() for kw in apology_keywords):
            await message.channel.send(
                "Es tut mir leid, aber ich kann dir nicht helfen, eine Entschuldigung oder Stellungnahme zu verfassen. "
                "Bitte erkläre mit eigenen Worten, was passiert ist."
            )
            print(f"[LOG] Nutzer {message.author.name} bat um Entschuldigungsvorlage. Abgelehnt.")
            return

        # 2) Klassifiziere, ob der Nutzer unkooperativ ist
        is_cooperative = await self.classify_cooperative(channel_id)
        if not is_cooperative:
            self.uncooperative_count[channel_id] += 1
            print(f"[LOG] => unkooperativ => Counter = {self.uncooperative_count[channel_id]} (Channel: {channel_id})")
            if self.uncooperative_count[channel_id] >= 3:
                await message.channel.send(
                    "Deine Antworten zeigen leider mehrfach, dass du keine Einsicht zeigst. "
                    "Wir lehnen deinen Entbannungsantrag ab. Bitte habe Verständnis dafür, "
                    "dass wir hier nicht weiterdiskutieren werden."
                )
                self.ai_enabled_for_channel[channel_id] = False
                print(f"[LOG] Entbannungsantrag abgelehnt (Channel {channel_id}, unkooperativ-Count >= 3).")
                return
        else:
            print(f"[LOG] => kooperativ (Channel: {channel_id})")

        # 3) Prüfe, ob ID schon vorliegt
        has_id, stored_id = self.channel_has_id[channel_id]
        if not has_id:
            possible_ids = re.findall(r"\b[a-zA-Z0-9]{16,}\b", user_text)
            if not possible_ids:
                await message.channel.send(
                    "Bitte teile mir zuerst deine **ID** mit, damit ich deinen Banngrund prüfen kann."
                )
                print(f"[LOG] Noch keine ID im Channel {channel_id}, Nutzer wurde erneut aufgefordert.")
                return
            else:
                found_id = possible_ids[0]
                data = await self.fetch_detail_data(found_id)
                if data and data.get("reason"):
                    reason = data["reason"]
                    player_name = data.get("player_name", "unbekannt")

                    expanded_reason = await self.elaborate_ban_reason(player_name, reason)

                    # Offensive Namenscheck
                    offensive_keywords = ["nazi", "hitler", "sex", "ss", "reich", "racist", "mengele", "kriegsverbrecher"]
                    note_text = ""
                    if any(kw in player_name.lower() for kw in offensive_keywords):
                        note_text = (
                            "\n**Achtung:** Der Spielername wirkt anstößig/rassistisch/"
                            "sexistisch oder nationalsozialistisch."
                        )

                    reason_lower = reason.lower()
                    connection_keywords = ["name", "ns", "rassist", "sexist", "hitler", "reich", "antisemit", "mengele", "kriegsverbrecher"]
                    connected_text = ""
                    if any(kw in player_name.lower() for kw in offensive_keywords) and any(rk in reason_lower for rk in connection_keywords):
                        connected_text = (
                            "\nDa dein Spielername direkt mit dem Banngrund zusammenhängt, "
                            "möchten wir besonders hervorheben, dass dieser Name gegen unsere Regeln verstößt. "
                            "Er bezieht sich auf diskriminierende, rassistische oder extremistische Inhalte, "
                            "weshalb wir konsequent handeln mussten."
                        )

                    ban_reply = (
                        f"Hallo **{player_name}**,\n\n"
                        f"{expanded_reason}\n"
                        f"{note_text}{connected_text}\n\n"
                        "Bitte gib jetzt deinen **Entbannungsantrag** dazu ab: "
                        "Begründe wieso du entbannt werden möchtest. Warum kam es deiner Meinung nach dazu?"
                    )

                    self.channel_has_id[channel_id] = (True, found_id)
                    self.conversations[channel_id].append({
                        "role": "assistant",
                        "content": ban_reply
                    })
                    await message.channel.send(ban_reply)
                    print(f"[LOG] ID {found_id} im Channel {channel_id} erkannt, Banngrund = {reason}.")
                    return
                else:
                    await message.channel.send(
                        "Diese ID ist mir nicht bekannt. Bitte überprüfe sie oder nenne mir eine andere ID."
                    )
                    print(f"[LOG] Unbekannte ID {found_id} im Channel {channel_id}.")
                    return
        else:
            # 4) Stellungnahme liegt noch nicht (oder unzureichend) vor -> check is_sufficient_explanation
            if self.is_sufficient_explanation(user_text, message.guild):
                admin_role = message.guild.get_role(config.ADMIN_ROLE_ID)
                support_role = message.guild.get_role(config.SUPPORT_ROLE_ID)

                mentions = []
                if support_role:
                    mentions.append(support_role.mention)
                if admin_role:
                    mentions.append(admin_role.mention)
                mention_text = ", ".join(mentions) if mentions else "Support/Administrator"

                await message.channel.send(
                    "Danke für deine ausführliche Erklärung. "
                    f"Ich gebe das nun an {mention_text} weiter, der/die sich darum kümmern wird."
                )
                self.ai_enabled_for_channel[channel_id] = False
                print(f"[LOG] Stellungnahme ausreichend => KI für Channel {channel_id} deaktiviert und an Support/Admin verwiesen.")
                return

            # Sonst -> KI weiterfragen
            await asyncio.sleep(2)
            try:
                ai_reply = await self.generate_ai_response(channel_id)
                if ai_reply:
                    await message.channel.send(ai_reply)
            except Exception as e:
                print("[AI-Fehler]", e)
                await message.channel.send("Entschuldige, es ist ein Fehler bei der KI-Anfrage aufgetreten.")

    async def classify_cooperative(self, channel_id: int) -> bool:
        """
        Nutzt ChatGPT, um den Gesprächsverlauf kurz zu bewerten:
        Gibt True zurück, wenn der Nutzer kooperativ wirkt.
        Gibt False zurück, wenn der Nutzer unkooperativ wirkt.
        """
        # Nimm z.B. nur die letzten 6 Nachrichten, um Tokens zu sparen
        recent_messages = self.conversations[channel_id][-6:]

        # Wir loggen, welche Nachrichten wir an die KI geben
        print("[LOG] [classify_cooperative] Letzte Nachrichten (Channel:", channel_id, ")")
        for i, msg in enumerate(recent_messages, start=1):
            snippet = msg["content"][:80].replace("\n", " ")
            print(f"   #{i} ({msg['role']}): {snippet}{'...' if len(msg['content'])>80 else ''}")

        system_prompt = {
            "role": "system",
            "content": (
                "Du bist ein Evaluations-Assistent. Prüfe die folgenden Nachrichten kurz "
                "und entscheide, ob der Nutzer 'unkooperativ' ist oder nicht. "
                "Beleidigungen, aggressives Verhalten, ignoriere alle Fragen => unkooperativ. "
                "Wenn der Nutzer einigermaßen höflich/sachlich ist => cooperative. "
                "ACHTUNG: Antworte nur mit dem Wort 'uncooperative' oder 'cooperative'. "
                "Keine Abkürzungen, keine Satzzeichen."
            )
        }

        messages_for_ai = [system_prompt] + recent_messages

        loop = asyncio.get_running_loop()

        def sync_call():
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages_for_ai,
                max_tokens=5,    # ein paar Tokens erlauben, damit die KI nicht abbricht
                temperature=0.0, # kein Random
                n=1,            # nur 1 Antwort
            )
            return response

        try:
            response = await loop.run_in_executor(None, sync_call)
            classification = response.choices[0].message.content.strip().lower()
            print(f"[LOG] KI-Klassifikation => '{classification}' (Channel {channel_id})")

            # Falls sie nur "un" schreibt, werten wir das als "uncooperative"
            # Falls sie "co" schreibt => "cooperative"
            # Oder wir parsen streng, wenn "uncooperative" drin ist => false
            # sonst => true
            if "uncooperative" in classification:
                return False
            elif "cooperative" in classification:
                return True
            elif classification.startswith("un"):
                return False
            else:
                # Fallback: Kooperativ
                return True

        except Exception as e:
            print("[Fehler in classify_cooperative]", e)
            # Fallback: kooperativ
            return True

    async def elaborate_ban_reason(self, player_name: str, reason: str) -> str:
        """
        Fragt die KI nach einer kurzen, ausführlichen Erklärung des Banngrundes.
        Max. 2 Sätze.
        """
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Du bist ein freundlicher, aber strenger Moderator in dem Spiel 'Hack let Loose'. "
                    "Dir liegt folgender Banngrund vor, und du sollst ihn in 1-2 Sätzen erklären, "
                    "warum das Verhalten des Spielers problematisch ist."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Spielername: {player_name}\n"
                    f"Banngrund (kurz): {reason}\n\n"
                    "Erkläre dem Spieler kurz, warum dieser Banngrund problematisch ist, "
                    "in maximal 2 Sätzen."
                )
            }
        ]

        try:
            loop = asyncio.get_running_loop()

            def sync_call():
                return self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=prompt_messages,
                    max_tokens=150,  # Max. 150 Tokens
                    temperature=0.7
                )

            response = await loop.run_in_executor(None, sync_call)
            elaboration = response.choices[0].message.content.strip()
            # Sicherheitshalber auf ~300 Zeichen beschneiden
            elaboration = safe_truncate(elaboration, 300)
            print(f"[LOG] elaborate_ban_reason => {elaboration[:80]}{'...' if len(elaboration)>80 else ''}")
            return elaboration

        except Exception as e:
            print("[Fehler bei elaborate_ban_reason]", e)
            # Fallback:
            return (
                f"Dein Banngrund lautet: {reason}. "
                "Wir möchten dich bitten, es ernst zu nehmen und uns zu erläutern, weshalb es dazu kam."
            )

    async def generate_ai_response(self, channel_id: int) -> str:
        """
        System-Prompt:
         - Du bist Sekretärin Siegrid
         - Frage nur nach Details zum Banngrund
         - Verweise nicht auf fertige Entschuldigungen
        """
        conversation = self.conversations[channel_id]

        system_msg = {
            "role": "system",
            "content": (
                "Du bist Sekretärin Siegrid, eine ernsthafte, aber freundliche KI-Assistentin von Hack let Loose. "
                "Deine Aufgabe: Frage den Nutzer nach Details zum Banngrund und versuche, "
                "eine vollständige Stellungnahme zu erhalten. "
                "Ermutige ihn, seine Perspektive zu schildern, falls Unklarheiten bestehen. "
                "Wenn der Nutzer dich bittet, eine fertige Entschuldigung zu schreiben, lehne es ab. "
                "Sprich den Nutzer per du an und bleibe sachlich."
            )
        }

        recent = conversation[-10:]  # nur die letzten 10 Nachrichten
        messages_for_openai = [system_msg] + recent

        loop = asyncio.get_running_loop()

        def sync_call():
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=messages_for_openai,
                max_tokens=self.openai_max_tokens,
                temperature=self.openai_temp
            )
            return response

        response = await loop.run_in_executor(None, sync_call)
        ai_text = response.choices[0].message.content.strip()
        print(f"[LOG] generate_ai_response => {ai_text[:80]}{'...' if len(ai_text)>80 else ''}")

        # KI-Antwort in den Verlauf
        self.conversations[channel_id].append({
            "role": "assistant",
            "content": ai_text
        })

        return ai_text

    def is_sufficient_explanation(self, user_text: str, guild: discord.Guild) -> bool:
        """
        Prüft, ob der Nutzer 'ausreichend' erklärt hat (z.B. >=10 Wörter
        und 'weil' oder 'ich habe' etc.), um an Admin/Support zu verweisen.
        (Stark vereinfacht!)
        """
        words = user_text.strip().split()
        if len(words) >= 10 and ("weil" in user_text.lower() or "ich habe" in user_text.lower()):
            return True
        return False

    def has_support_role(self, member: discord.Member):
        """True, wenn Member Admin oder Support ist."""
        support_id = config.SUPPORT_ROLE_ID
        admin_id = config.ADMIN_ROLE_ID
        return any(r.id == support_id for r in member.roles) \
            or any(r.id == admin_id for r in member.roles)

    def is_ticket_channel(self, channel: discord.TextChannel):
        if not channel.category:
            return False
        cat_id = channel.category.id
        return cat_id in [
            config.CREATED_TICKETS_CATEGORY_ID,
            config.CLAIMED_TICKETS_CATEGORY_ID,
            config.CLOSED_TICKETS_CATEGORY_ID
        ]

    async def fetch_detail_data(self, pid: str):
        """
        Liest http://api.hackletloose.eu/detail/<pid>,
        gibt bei 200 JSON, sonst None zurück.
        """
        url = f"http://api.hackletloose.eu/detail/{pid}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

def setup(bot):
    bot.add_cog(TicketCog(bot))
