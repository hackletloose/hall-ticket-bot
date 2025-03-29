# cogs/ticket_cog.py

import discord
from discord.ext import commands
import re
import aiohttp
import asyncio
import unicodedata
from collections import defaultdict

# OCR-Imports
import pytesseract
from PIL import Image
import io

from openai import OpenAI

from utils import config, database

##############################################################################
# Klassendefinitionen
##############################################################################

class CreateTicketView(discord.ui.View):
    """
    View mit einem Button "Ticket erstellen".
    Beim Klick rufen wir 'create_ticket_callback' auf,
    die auf das Cog selbst zugreift.
    """
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Ticket erstellen", style=discord.ButtonStyle.danger)
    async def create_ticket_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.create_ticket(interaction)


class TicketAdminView(discord.ui.View):
    """
    View mit den drei Buttons "Ticket beanspruchen", "Ticket schließen", "Ticket löschen".
    """
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Ticket beanspruchen", style=discord.ButtonStyle.success)
    async def claim_ticket_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger)
    async def close_ticket_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.close_ticket(interaction)

    @discord.ui.button(label="Ticket löschen", style=discord.ButtonStyle.danger)
    async def delete_ticket_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.delete_ticket(interaction)

##############################################################################
# Hilfsfunktionen
##############################################################################

def safe_truncate(text: str, max_chars: int) -> str:
    """
    Kürzt den Text auf max_chars Zeichen und fügt '... (gekürzt)' an, wenn zu lang.
    (Wird hier nicht mehr aktiv genutzt, aber wir lassen die Funktion im Skript.)
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

##############################################################################
# Haupt-Cog: TicketCog
##############################################################################

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
        self.channel_has_id = defaultdict(lambda: (False, ""))

        # Zähler für uneinsichtiges Verhalten
        self.uncooperative_count = defaultdict(int)

        # OpenAI Setup
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.openai_model = config.OPENAI_MODEL or "gpt-3.5-turbo"
        self.openai_temp = 0.7
        self.openai_max_tokens = 1000

    @commands.Cog.listener()
    async def on_ready(self):
        print("[LOG] [TicketCog] Ticket-Cog ist bereit.")

    # ------------------------------------------------------------------------
    # Slash-Befehl: /setup_ticket_button
    # ------------------------------------------------------------------------
    @commands.slash_command(
        name="setup_ticket_button",
        description="Erstellt im aktuellen Kanal eine Nachricht mit einem Ticket-Button (nur Admin)."
    )
    @commands.has_role(config.ADMIN_ROLE_ID)
    async def setup_ticket_button(self, ctx: discord.ApplicationContext):
        """
        Legt eine neue Nachricht mit dem Ticket-Erstell-Button an
        und speichert channel_id + message_id in der DB.
        """
        print("[LOG] Slash-Befehl '/setup_ticket_button' wurde aufgerufen.")
        embed = discord.Embed(
            title="Ticket-Hilfe",
            description=(
                "Klicke auf den Button, um ein neues Ticket zu erstellen. "
                "Wenn du gebannt wurdest, nenne bitte deine ID, damit wir dir Auskunft geben können."
            ),
            color=discord.Color.green()
        )

        view = CreateTicketView(self)
        msg = await ctx.channel.send(embed=embed, view=view)

        self.db.save_bot_setting("TICKET_BUTTON_CHANNEL_ID", str(ctx.channel.id))
        self.db.save_bot_setting("TICKET_BUTTON_MESSAGE_ID", str(msg.id))

        await ctx.respond("Ticket-Button wurde platziert und in der DB registriert.", ephemeral=True)
        print(f"[LOG] Ticket-Button im Kanal {ctx.channel.id}, Nachricht {msg.id} gespeichert.")

    # ------------------------------------------------------------------------
    # create_ticket
    # ------------------------------------------------------------------------
    async def create_ticket(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return

        user = interaction.user
        guild = interaction.guild

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
                await interaction.followup.send("Fehler: Ticket-Kategorie nicht gefunden.", ephemeral=True)
                return

            if isinstance(user, discord.Member) and user.nick:
                user_name = user.nick
            else:
                user_name = user.name

            channel_name = f"{user_name.replace(' ', '-')[:20]}-{ticket_id}"
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

            self.db.log_ticket_created(ticket_id, user.id, user_name, ticket_channel.id)

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

            view = TicketAdminView(self)
            admin_msg = await ticket_channel.send(content=user.mention, embed=embed, view=view)

            self.db.log_ticket_admin_message(ticket_id, admin_msg.id)

            print(f"[LOG] Ticket #{ticket_id} erstellt von {user.name} (ID: {user.id}).")

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

    # ------------------------------------------------------------------------
    # claim_ticket
    # ------------------------------------------------------------------------
    async def claim_ticket(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return

        if not self.has_support_role(interaction.user):
            await interaction.followup.send("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            return

        channel = interaction.channel
        guild = interaction.guild

        parts = channel.name.split("-")
        if len(parts) < 2:
            await interaction.followup.send("Dies scheint kein gültiger Ticket-Kanal zu sein.", ephemeral=True)
            return

        try:
            ticket_id = int(parts[-1])
        except ValueError:
            await interaction.followup.send("Konnte Ticket-ID nicht bestimmen.", ephemeral=True)
            return

        claimed_cat = guild.get_channel(config.CLAIMED_TICKETS_CATEGORY_ID)
        if claimed_cat:
            await channel.edit(category=claimed_cat, sync_permissions=True)

        support_role = guild.get_role(config.SUPPORT_ROLE_ID)
        if support_role:
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

        await interaction.followup.send(
            f"Ticket #{ticket_id} wurde von {interaction.user.mention} beansprucht.",
            ephemeral=False
        )
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} beansprucht.")

    # ------------------------------------------------------------------------
    # close_ticket
    # ------------------------------------------------------------------------
    async def close_ticket(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            return

        if not self.has_support_role(interaction.user):
            await interaction.followup.send("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            return

        channel = interaction.channel
        guild = interaction.guild

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

        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
        transcript_text = "\n".join(lines)
        self.db.save_transcript(ticket_id, transcript_text)
        await channel.send("Transkript wurde automatisch erstellt und gespeichert.")

        closed_cat = guild.get_channel(config.CLOSED_TICKETS_CATEGORY_ID)
        if closed_cat:
            await channel.edit(category=closed_cat, sync_permissions=True)

        viewer_role = guild.get_role(config.VIEWER_ROLE_ID)
        if viewer_role:
            await channel.set_permissions(viewer_role, view_channel=True, send_messages=False)

        self.ai_enabled_for_channel[channel.id] = False
        await channel.send("Ticket ist nun geschlossen.")
        await interaction.followup.send(f"Ticket #{ticket_id} wurde geschlossen.", ephemeral=True)
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} geschlossen.")

    # ------------------------------------------------------------------------
    # delete_ticket
    # ------------------------------------------------------------------------
    async def delete_ticket(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return

        if not self.has_support_role(interaction.user):
            await interaction.followup.send("Du bist kein Supporter/Admin und darfst das nicht!", ephemeral=True)
            return

        channel = interaction.channel
        guild = interaction.guild

        parts = channel.name.split("-")
        if len(parts) < 2:
            await interaction.followup.send("Dies scheint kein gültiger Ticket-Kanal zu sein.", ephemeral=True)
            return

        try:
            ticket_id = int(parts[-1])
        except ValueError:
            await interaction.followup.send("Konnte Ticket-ID nicht bestimmen.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Ticket #{ticket_id} wird nun gelöscht (Transkript bleibt gespeichert).",
            ephemeral=True
        )

        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        lines = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
        transcript_text = "\n".join(lines)
        self.db.save_transcript(ticket_id, transcript_text)

        self.db.log_ticket_deleted(ticket_id)
        await channel.send("Ticket-Kanal wird gelöscht...")

        self.ai_enabled_for_channel[channel.id] = False
        await channel.delete()
        print(f"[LOG] Ticket #{ticket_id} wurde von {interaction.user.name} gelöscht.")

    ############################################################################
    # on_message: KI-Logik (inkl. OCR)
    ############################################################################
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
            return

        # Nur in Ticket-Kanälen
        if not self.is_ticket_channel(message.channel):
            return

        # KI aktiv?
        if not self.ai_enabled_for_channel.get(channel_id, False):
            return

        user_text = normalize_id_string(message.content)
        self.conversations[channel_id].append({"role": "user", "content": user_text})

        print(f"[LOG] Neue Nachricht im Channel {channel_id} von {message.author.name}: {user_text}")

        # 1) Entschuldigung?
        apology_keywords = [
            "entschuldigung schreiben", "formulieren", "apology", "help me write",
            "schreibe mir eine entschuldigung", "schreibe mir ein statement"
        ]
        if any(kw in user_text.lower() for kw in apology_keywords):
            await message.channel.send(
                "Es tut mir leid, aber ich kann dir nicht helfen, eine Entschuldigung oder Stellungnahme zu verfassen. "
                "Bitte erkläre mit eigenen Worten, was passiert ist."
            )
            return

        # 2) Kooperativ?
        is_cooperative = await self.classify_cooperative(channel_id)
        if not is_cooperative:
            self.uncooperative_count[channel_id] += 1
            if self.uncooperative_count[channel_id] >= 3:
                await message.channel.send(
                    "Deine Antworten zeigen leider mehrfach, dass du keine Einsicht zeigst. "
                    "Wir lehnen deinen Entbannungsantrag ab. Bitte habe Verständnis."
                )
                self.ai_enabled_for_channel[channel_id] = False
                return
        else:
            print(f"[LOG] => kooperativ (Channel: {channel_id})")

        # 3) ID?
        has_id, stored_id = self.channel_has_id[channel_id]
        if not has_id:
            possible_ids = re.findall(r"\b[a-zA-Z0-9]{16,}\b", user_text)
            if not possible_ids:
                await message.channel.send(
                    "Bitte teile mir zuerst deine **ID** mit, damit ich deinen Banngrund prüfen kann."
                )
                return
            else:
                found_id = possible_ids[0]
                data = await self.fetch_detail_data(found_id)
                if data and data.get("reason"):
                    reason = data["reason"]
                    player_name = data.get("player_name", "unbekannt")

                    # OCR => attachments
                    attachments = data.get("attachments", [])
                    if attachments and isinstance(attachments, list):
                        summaries = []
                        for attachment_url in attachments:
                            print(f"[LOG] Starte OCR für Anhang: {attachment_url}")
                            full_ocr_text = await self._ocr_from_url(attachment_url)
                            print(f"[LOG] OCR beendet. Länge des erkannten Textes: {len(full_ocr_text)} Zeichen.")

                            if full_ocr_text.strip():
                                print("[LOG] Starte Zusammenfassung des OCR-Texts...")
                                summary = await self.summarize_ocr_text(full_ocr_text)
                                print(f"[LOG] Zusammenfassung erstellt: {summary}")
                                summaries.append(summary)
                            else:
                                print("[LOG] Kein Text erkannt (OCR-Ergebnis leer).")
                                summaries.append("")

                        # Zusammenfassungen ins eigentliche reason einfließen lassen,
                        # ohne sie einzeln aufzuzählen
                        if summaries:
                            combined_summaries = " ".join(summaries).strip()
                            if combined_summaries:
                                reason += f" {combined_summaries}"

                    # Banngrund durch die KI elaborieren
                    expanded_reason = await self.elaborate_ban_reason(player_name, reason)

                    # Endgültige Nachricht an den Spieler (ohne Bild-für-Bild-Erklärungen):
                    ban_reply = (
                        f"Hallo **{player_name}**,\n\n"
                        f"{expanded_reason}\n\n"
                        "Bitte gib jetzt deinen **Entbannungsantrag** dazu ab: "
                        "Warum möchtest du entbannt werden und wie siehst du dein Verhalten?"
                    )

                    self.channel_has_id[channel_id] = (True, found_id)
                    self.conversations[channel_id].append({"role": "assistant", "content": ban_reply})
                    await message.channel.send(ban_reply)
                    return
                else:
                    await message.channel.send(
                        "Diese ID ist mir nicht bekannt. Bitte überprüfe sie oder nenne mir eine andere ID."
                    )
                    return
        else:
            # 4) Stellungnahme ausreichend?
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
                    f"Danke für deine ausführliche Erklärung. Ich gebe das nun an {mention_text} weiter."
                )
                self.ai_enabled_for_channel[channel_id] = False
                return

            # Sonst -> KI fragt weiter
            await asyncio.sleep(2)
            try:
                ai_reply = await self.generate_ai_response(channel_id)
                if ai_reply:
                    await message.channel.send(ai_reply)
            except Exception as e:
                print("[AI-Fehler]", e)
                await message.channel.send("Entschuldige, es ist ein Fehler bei der KI-Anfrage aufgetreten.")

    # ------------------------------------------------------------------------
    # OCR-Methoden
    # ------------------------------------------------------------------------
    async def _ocr_from_url(self, image_url: str) -> str:
        """
        Lädt das Bild, führt OCR via pytesseract aus und gibt den erkannten Text zurück.
        """
        print(f"[LOG] [OCR] Versuche, Bild herunterzuladen: {image_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        img = Image.open(io.BytesIO(image_bytes))
                        print("[LOG] [OCR] Bild erfolgreich geladen, starte Tesseract...")
                        text = pytesseract.image_to_string(img, lang="deu")
                        print("[LOG] [OCR] Tesseract fertig.")
                        return text
                    else:
                        print(f"[ERROR] [OCR] Download fehlgeschlagen, Status: {resp.status}")
                        return ""
        except Exception as e:
            print(f"[ERROR] [OCR] Fehler bei OCR von {image_url}: {e}")
            return ""

    async def summarize_ocr_text(self, ocr_text: str) -> str:
        """
        Erstellt via GPT eine kurze Zusammenfassung des OCR-Textes,
        ohne diesen 1:1 zu wiederholen.
        """
        print("[LOG] [OCR] Starte Zusammenfassungs-Request an OpenAI.")
        system_prompt = (
            "Du bist ein Assistent, der aus dem folgenden OCR-Text "
            "eine kurze, deutsche Zusammenfassung erstellt. "
            "Bitte verwende Du-Formulierung falls angemessen. "
            "Verzichte auf exaktes Zitieren langer Passagen."
        )
        user_prompt = f"OCR-Text:\n{ocr_text}\n\nErstelle eine kurze Zusammenfassung:"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        loop = asyncio.get_running_loop()

        def sync_call():
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                max_tokens=200,
                temperature=0.7
            )
            return response

        try:
            response = await loop.run_in_executor(None, sync_call)
            summary = response.choices[0].message.content.strip()
            print("[LOG] [OCR] Zusammenfassung erfolgreich erhalten.")
            return summary
        except Exception as e:
            print("[Fehler bei summarize_ocr_text]", e)
            return ""

    # ------------------------------------------------------------------------
    # KI-Hilfsmethoden
    # ------------------------------------------------------------------------
    async def classify_cooperative(self, channel_id: int) -> bool:
        recent_messages = self.conversations[channel_id][-6:]
        system_prompt = {
            "role": "system",
            "content": (
                "Du bist ein Evaluations-Assistent. Prüfe die folgenden Nachrichten kurz "
                "und entscheide, ob der Nutzer 'unkooperativ' ist oder nicht. "
                "Beleidigungen, aggressives Verhalten, ignoriert alle Fragen => unkooperativ. "
                "Wenn der Nutzer einigermaßen höflich/sachlich ist => cooperative. "
                "Antworte nur mit 'uncooperative' oder 'cooperative'."
            )
        }

        messages_for_ai = [system_prompt] + recent_messages
        loop = asyncio.get_running_loop()

        def sync_call():
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=messages_for_ai,
                max_tokens=5,
                temperature=0.0
            )
            return response

        try:
            response = await loop.run_in_executor(None, sync_call)
            classification = response.choices[0].message.content.strip().lower()

            if "uncooperative" in classification:
                return False
            elif "cooperative" in classification:
                return True
            elif classification.startswith("un"):
                return False
            else:
                return True
        except Exception as e:
            print("[Fehler in classify_cooperative]", e)
            return True

    async def elaborate_ban_reason(self, player_name: str, reason: str) -> str:
        """
        Spreche den Spieler direkt in Du-Form an, ohne weitere Begrüßung.
        """
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Du bist ein freundlicher, aber strenger Moderator in dem Spiel 'Hell let Loose'. "
                    "Dir liegt folgender Banngrund vor, und du sollst ihm erklären, "
                    "warum das Verhalten problematisch ist. Sprich den Spieler direkt in der Du-Form an, "
                    "aber vermeide eine gesonderte Begrüßung wie 'Hallo XYZ'."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Spielername: {player_name}\n"
                    f"Banngrund (kurz): {reason}\n\n"
                    "Erkläre in Du-Form, warum dieses Verhalten inakzeptabel ist, "
                    "ohne den Spieler erneut mit einem 'Hallo' oder Namen anzureden."
                )
            }
        ]

        loop = asyncio.get_running_loop()

        def sync_call():
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=prompt_messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response

        try:
            response = await loop.run_in_executor(None, sync_call)
            elaboration = response.choices[0].message.content.strip()
            return elaboration
        except Exception as e:
            print("[Fehler bei elaborate_ban_reason]", e)
            return (
                "Dein Verhalten widerspricht unseren Richtlinien und schadet der Community-Atmosphäre. "
                "Bitte erkläre, warum es aus deiner Sicht dazu kam."
            )

    async def generate_ai_response(self, channel_id: int) -> str:
        conversation = self.conversations[channel_id]
        system_msg = {
            "role": "system",
            "content": (
                "Du bist Sekretärin Siegrid, eine ernsthafte, aber freundliche KI-Assistentin von Hack let Loose. "
                "Sprich den Nutzer direkt in der Du-Form an. Wenn er dich bittet, "
                "eine fertige Entschuldigung zu schreiben, lehne es ab."
            )
        }

        recent = conversation[-10:]
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

        self.conversations[channel_id].append({
            "role": "assistant",
            "content": ai_text
        })
        return ai_text

    # ------------------------------------------------------------------------
    # Hilfsprüfungen
    # ------------------------------------------------------------------------
    def is_sufficient_explanation(self, user_text: str, guild: discord.Guild) -> bool:
        words = user_text.strip().split()
        return (len(words) >= 10) and ("weil" in user_text.lower() or "ich habe" in user_text.lower())

    def has_support_role(self, member: discord.Member) -> bool:
        support_id = config.SUPPORT_ROLE_ID
        admin_id = config.ADMIN_ROLE_ID
        return any(r.id == support_id for r in member.roles) or any(r.id == admin_id for r in member.roles)

    def is_ticket_channel(self, channel: discord.TextChannel) -> bool:
        if not channel.category:
            return False
        cat_id = channel.category.id
        return cat_id in [
            config.CREATED_TICKETS_CATEGORY_ID,
            config.CLAIMED_TICKETS_CATEGORY_ID,
            config.CLOSED_TICKETS_CATEGORY_ID
        ]

    async def fetch_detail_data(self, pid: str):
        url = f"http://api.hackletloose.eu/detail/{pid}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None


def setup(bot: commands.Bot):
    bot.add_cog(TicketCog(bot))
