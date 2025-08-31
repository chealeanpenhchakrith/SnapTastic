import os
import json
import re
import discord
import asyncio
from pathlib import Path
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
REPORTER_ROLE_ID = os.getenv("REPORTER_ROLE_ID")
REPORTER_BORDEAUX_ROLE_ID = os.getenv("REPORTER_BORDEAUX_ROLE_ID")
PHOTO_CHANNEL_ID = int(os.getenv("PHOTO_CHANNEL_ID", "0"))
PHOTO_RESULT_CHANNEL_ID = int(os.getenv("PHOTO_RESULT_CHANNEL_ID", "0"))
VOTE_EMOJI = os.getenv("VOTE_EMOJI", "🗳️")

# === Monthly contest settings ===
MONTHLY_ENABLED = os.getenv("MONTHLY_ENABLED", "1") == "1"
MONTHLY_VOTE_DURATION_MIN = int(os.getenv("MONTHLY_VOTE_DURATION_MIN", "2880"))
MONTHLY_VOTE_EMOJI = os.getenv("MONTHLY_VOTE_EMOJI", VOTE_EMOJI)
# ================================

TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")
SHARE_WEEKDAY = int(os.getenv("SHARE_WEEKDAY", "6"))
SHARE_HOUR = int(os.getenv("SHARE_HOUR", "21"))
SHARE_MIN = int(os.getenv("SHARE_MIN", "39"))

OPEN_WEEKDAY = int(os.getenv("OPEN_WEEKDAY", "6"))
OPEN_HOUR = int(os.getenv("OPEN_HOUR", "21"))
OPEN_MIN = int(os.getenv("OPEN_MIN", "40"))

RESULT_WEEKDAY = int(os.getenv("RESULT_WEEKDAY", "6"))
RESULT_HOUR = int(os.getenv("RESULT_HOUR", "21"))
RESULT_MIN = int(os.getenv("RESULT_MIN", "41"))

TEST_MODE = os.getenv("TEST_MODE", "0") == "1"
TEST_WAIT_SEC = int(os.getenv("TEST_WAIT_SEC", "10"))

tz = ZoneInfo(TIMEZONE)

user_submissions = defaultdict(int)
last_photo_call = None

# Simple JSON-backed winners store
class WinnersStore:
    def __init__(self, path: Path):
        self.path = path
        self._winners = set()
        self._monthly_winners = set()
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                self._winners = set(int(x) for x in data.get("winners", []))
                self._monthly_winners = set(int(x) for x in data.get("monthly_winners", []))
            else:
                self.save()
        except Exception:
            self._winners = set()
            self._monthly_winners = set()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump({
                    "winners": sorted(self._winners),
                    "monthly_winners": sorted(self._monthly_winners)
                }, f, indent=2)
        except Exception:
            pass

    def add(self, user_id: int):
        if user_id not in self._winners:
            self._winners.add(user_id)
            self.save()

    def remove_weekly(self, user_id: int) -> bool:
        if user_id in self._winners:
            self._winners.remove(user_id)
            self.save()
            return True
        return False

    def remove_monthly(self, user_id: int) -> bool:
        if user_id in self._monthly_winners:
            self._monthly_winners.remove(user_id)
            self.save()
            return True
        return False

    def contains(self, user_id: int) -> bool:
        return user_id in self._winners

    def all(self):
        return sorted(self._winners)

    # Monthly winners methods
    def add_monthly(self, user_id: int):
        if user_id not in self._monthly_winners:
            self._monthly_winners.add(user_id)
            self.save()

    def monthly_contains(self, user_id: int) -> bool:
        return user_id in self._monthly_winners

    def monthly_all(self):
        return sorted(self._monthly_winners)

winners_store = WinnersStore(Path(__file__).with_name("winners.json"))

# === Monthly persistence (weekly winners + monthly contest state) ===
class MonthlyStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "weekly": [],
            "week_no": 0,
            "last_monthly_week_no": 0,
            "active": None
        }
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as f:
                    self.data = json.load(f)
            else:
                self.save()
        except Exception:
            self.data = {
                "weekly": [],
                "week_no": 0,
                "last_monthly_week_no": 0,
                "active": None
            }
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def begin_new_week(self):
        self.data["week_no"] = int(self.data.get("week_no", 0)) + 1
        self.save()

    def add_weekly_winner(self, author_id: int, author_mention: str, image_url: str, votes: int):
        entry = {
            "author_id": author_id,
            "author_mention": author_mention,
            "image_url": image_url,
            "votes": int(votes),
            "week_no": int(self.data.get("week_no", 0)),
            "created_at": datetime.now(tz).isoformat()
        }
        self.data["weekly"].append(entry)
        self.save()

    def months_due(self) -> bool:
        return (int(self.data.get("week_no", 0)) - int(self.data.get("last_monthly_week_no", 0))) >= 4

    def get_last_4_weeks_entries(self):
        last_done = int(self.data.get("last_monthly_week_no", 0))
        target_weeks = {last_done + 1, last_done + 2, last_done + 3, last_done + 4}
        return [e for e in self.data.get("weekly", []) if int(e.get("week_no", 0)) in target_weeks]

    def mark_monthly_consumed(self):
        self.data["last_monthly_week_no"] = int(self.data.get("last_monthly_week_no", 0)) + 4
        self.save()

    def set_active(self, thread_id: int, thread_jump_url: str, opened_at_iso: str, ends_at_iso: str):
        self.data["active"] = {
            "thread_id": thread_id,
            "thread_jump_url": thread_jump_url,
            "opened_at": opened_at_iso,
            "ends_at": ends_at_iso,
            "closed": False
        }
        self.save()

    def clear_active(self):
        self.data["active"] = None
        self.save()

    def get_active(self):
        return self.data.get("active")

    def set_active_closed(self):
        if self.data.get("active"):
            self.data["active"]["closed"] = True
            self.save()

    def parse_active_ends_at(self):
        active = self.get_active()
        if not active:
            return None
        try:
            return datetime.fromisoformat(active["ends_at"])
        except Exception:
            return None

monthly_store = MonthlyStore(Path(__file__).with_name("monthly.json"))
# =====================================================================

# === Monthly helpers ===
async def maybe_open_monthly_contest():
    if not MONTHLY_ENABLED:
        return

    active = monthly_store.get_active()
    if active and not active.get("closed"):
        return

    if not monthly_store.months_due():
        return

    entries = monthly_store.get_last_4_weeks_entries()
    if not entries:
        return

    photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
    if photo_channel is None:
        print("maybe_open_monthly_contest: photo channel not found")
        return

    thread_name = f"🏅 Concours Mensuel - {datetime.now(tz).strftime('%d/%m/%Y')}"
    thread = await photo_channel.create_thread(
        name=thread_name,
        auto_archive_duration=1440,
        reason="Automated monthly open votes"
    )

    intro = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

🎉 Le **Concours Mensuel** est ouvert ! Voici les photos gagnantes des 4 dernières semaines.

Pour voter, réagissez avec {MONTHLY_VOTE_EMOJI} sur vos photos préférées.

• Vous pouvez voter pour plusieurs photos
• Les votes se terminent automatiquement dans {MONTHLY_VOTE_DURATION_MIN // 60}h
• Le ou la gagnant(e) mensuel(le) sera annoncé(e) ici et dans le canal des résultats
"""
    await thread.send(intro)

    for e in entries:
        content = f"Gagnant semaine #{e['week_no']} • {e['author_mention']}"
        try:
            msg = await thread.send(
                content=content,
                embed=discord.Embed().set_image(url=e["image_url"])
            )
            try:
                await msg.add_reaction(MONTHLY_VOTE_EMOJI)
            except Exception:
                await msg.add_reaction("✅")
        except Exception as ex:
            print("maybe_open_monthly_contest: failed to post one monthly photo:", ex)
            continue

    opened_at = datetime.now(tz)
    ends_at = opened_at + timedelta(minutes=MONTHLY_VOTE_DURATION_MIN)

    monthly_store.set_active(
        thread_id=thread.id,
        thread_jump_url=thread.jump_url,
        opened_at_iso=opened_at.isoformat(),
        ends_at_iso=ends_at.isoformat(),
    )
    monthly_store.mark_monthly_consumed()

    bot.loop.create_task(schedule_monthly_close())


async def schedule_monthly_close():
    active = monthly_store.get_active()
    if not active or active.get("closed"):
        return

    ends_at = monthly_store.parse_active_ends_at()
    if not ends_at:
        return

    now = datetime.now(tz)
    wait_seconds = max(0, int((ends_at - now).total_seconds()))
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)

    try:
        await close_monthly_contest_auto()
    except Exception as e:
        print("schedule_monthly_close error:", e)


async def close_monthly_contest_auto():
    results_channel = bot.get_channel(PHOTO_RESULT_CHANNEL_ID)
    if results_channel is None:
        print("close_monthly_contest_auto: results channel not found")
        return

    active = monthly_store.get_active()
    if not active or active.get("closed"):
        print("close_monthly_contest_auto: no active monthly contest")
        return

    thread = bot.get_channel(active["thread_id"])
    if thread is None:
        try:
            thread = await bot.fetch_channel(active["thread_id"])
        except Exception:
            thread = None

    if thread is None:
        print("close_monthly_contest_auto: monthly thread not found")
        monthly_store.set_active_closed()
        monthly_store.clear_active()
        return

    entries = []
    async for message in thread.history(limit=None):
        if message.embeds and len(message.embeds) > 0:
            content = (message.content or "").strip()

            author_id = None
            author_mention = None
            m = re.search(r"<@!?(\d+)>", content)
            if m:
                author_id = int(m.group(1))
                author_mention = f"<@{author_id}>"

            try:
                img_url = message.embeds[0].image.url
            except Exception:
                img_url = None

            votes = 0
            found_vote_reaction = False
            for reaction in message.reactions:
                if str(reaction.emoji) == MONTHLY_VOTE_EMOJI:
                    votes = max(0, reaction.count - 1)
                    found_vote_reaction = True
                    break
            if not found_vote_reaction:
                for reaction in message.reactions:
                    if str(reaction.emoji) == "✅":
                        votes = max(0, reaction.count - 1)
                        break

            if img_url and author_id:
                entries.append({
                    "author_id": author_id,
                    "author_mention": author_mention or f"<@{author_id}>",
                    "image_url": img_url,
                    "votes": votes
                })

    if not entries:
        await results_channel.send("❌ Aucun vote mensuel n'a été trouvé.")
        try:
            await results_channel.send(f"📁 Fil du concours mensuel : {thread.jump_url}")
        except Exception:
            pass
        try:
            await thread.edit(archived=False, locked=True)
        except Exception:
            pass
        monthly_store.set_active_closed()
        monthly_store.clear_active()
        print("close_monthly_contest_auto: no votes found")
        return

    # Exclude past monthly winners from eligibility
    eligible = [e for e in entries if not winners_store.monthly_contains(e["author_id"])]

    if not eligible:
        await results_channel.send("⚠️ Aucun gagnant mensuel éligible (tous ont déjà gagné auparavant).")
        try:
            await results_channel.send(f"📁 Fil du concours mensuel : {thread.jump_url}")
        except Exception:
            pass
        try:
            await thread.edit(archived=False, locked=True)
        except Exception:
            pass
        monthly_store.set_active_closed()
        monthly_store.clear_active()
        print("close_monthly_contest_auto: no eligible monthly winners")
        return

    max_votes = max(e["votes"] for e in eligible)
    winners = [e for e in eligible if e["votes"] == max_votes]

    if len(winners) == 1:
        w = winners[0]
        result = f"🏅 **Gagnant(e) du Concours Mensuel : {w['author_mention']} avec {max_votes} votes !**\n\nFélicitations ! Voici la photo gagnante :"
        await results_channel.send(result)
        await results_channel.send(embed=discord.Embed().set_image(url=w["image_url"]))
    else:
        authors = ", ".join(e["author_mention"] for e in winners)
        result = f"🏅 **Égalité au Concours Mensuel avec {max_votes} votes chacun !**\n\nFélicitations à {authors} !\n\nVoici les photos gagnantes :"
        await results_channel.send(result)
        for e in winners:
            await results_channel.send(embed=discord.Embed().set_image(url=e["image_url"]))

    # Persist monthly winners so they can't win again
    for e in winners:
        winners_store.add_monthly(e["author_id"])

    try:
        await results_channel.send(f"📁 Fil du concours mensuel : {thread.jump_url}")
    except Exception:
        pass

    await asyncio.sleep(2)
    try:
        await thread.edit(archived=False, locked=True)
    except Exception:
        pass

    monthly_store.set_active_closed()
    monthly_store.clear_active()
    print("close_monthly_contest_auto: done")
# === End monthly helpers ===

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Helpers (non-interactive versions)
async def send_partage_message_auto():
    global last_photo_call
    photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
    if photo_channel is None:
        print("send_partage_message_auto: photo channel not found")
        return
    last_photo_call = datetime.now(timezone.utc)
    message = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

Une **nouvelle semaine** commence ✨ 
C'est le moment idéal pour partager vos plus belles photos dans ce canal 📸

**__Rappel des règles__** :

• Vous pouvez poster **1 seule photo** jusqu'à samedi 00:00
• Merci de ne pas écrire de texte dans ce canal (photo uniquement)
• Les votes auront lieu de **samedi 00:00** à **dimanche 18:00** 🗳️
• Le ou la gagnant(e) sera annoncé(e) **dimanche soir** 🏆

Bonne chance à toutes et à tous, et amusez-vous bien 🎉"""
    try:
        await photo_channel.send(content=message, allowed_mentions=discord.AllowedMentions(roles=True))
        print("Automated: partage message sent")
    except Exception as e:
        print("send_partage_message_auto error:", e)

async def create_vote_thread_from_photos_auto():
    global last_photo_call, user_submissions
    photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
    if photo_channel is None:
        print("create_vote_thread_from_photos_auto: photo channel not found")
        return None

    messages = []
    async for msg in photo_channel.history(limit=500):
        if last_photo_call and msg.created_at < last_photo_call:
            continue
        if msg.attachments:
            messages.append(msg)

    if not messages:
        return None

    thread = await photo_channel.create_thread(
        name=f"📊 Votes - {datetime.now(tz).strftime('%d/%m/%Y')}",
        auto_archive_duration=1440,
        reason="Automated open votes"
    )

    intro = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

**🗳️ La phase de votes est ouverte !**

Pour voter, réagissez avec {VOTE_EMOJI} sur vos photos préférées.

• Vous pouvez voter pour plusieurs photos
• Les votes sont ouverts jusqu'à dimanche 18:00
• Le/la gagnant(e) sera annoncé(e) dimanche soir

**📸 __Voici les photos soumises :__**
⠀"""
    await thread.send(intro)

    for msg in reversed(messages):
        try:
            photo_message = await thread.send(
                content=f"Photo de {msg.author.mention}:",
                embed=discord.Embed().set_image(url=msg.attachments[0].url)
            )
            try:
                await photo_message.add_reaction(VOTE_EMOJI)
            except Exception:
                await photo_message.add_reaction("✅")
        except Exception:
            print("create_vote_thread_from_photos_auto: failed to post one photo")
            continue

    user_submissions.clear()
    last_photo_call = None
    return thread

async def close_votes_and_announce_auto():
    results_channel = bot.get_channel(PHOTO_RESULT_CHANNEL_ID)
    if results_channel is None:
        print("close_votes_and_announce_auto: results channel not found")
        return

    voting_thread = None
    for g in bot.guilds:
        active_threads = await g.active_threads()
        for thread in active_threads:
            if thread.parent_id == PHOTO_CHANNEL_ID and thread.name.startswith("📊 Votes"):
                voting_thread = thread
                break
        if voting_thread:
            break

    if not voting_thread:
        print("close_votes_and_announce_auto: no active voting thread found")
        return

    entries = []
    async for message in voting_thread.history(limit=None):
        if message.embeds and len(message.embeds) > 0:
            content = (message.content or "").strip()
            author_mention = None
            author_id = None
            if content.startswith("Photo de "):
                part = content.split("Photo de ", 1)[1].rstrip(":").strip()
                author_mention = part
                m = re.match(r"<@!?(\d+)>", part)
                if m:
                    author_id = int(m.group(1))

            try:
                img_url = message.embeds[0].image.url
            except Exception:
                img_url = None

            votes = 0
            found_vote_reaction = False
            for reaction in message.reactions:
                if str(reaction.emoji) == VOTE_EMOJI:
                    votes = max(0, reaction.count - 1)
                    found_vote_reaction = True
                    break
            if not found_vote_reaction:
                for reaction in message.reactions:
                    if str(reaction.emoji) == "✅":
                        votes = max(0, reaction.count - 1)
                        break

            if img_url and author_id:
                entries.append({
                    "message": message,
                    "author_id": author_id,
                    "author_mention": author_mention or f"<@{author_id}>",
                    "image_url": img_url,
                    "votes": votes
                })

    if not entries:
        await results_channel.send("❌ Aucun vote n'a été trouvé.")
        print("close_votes_and_announce_auto: no votes found")
        return

    eligible = [e for e in entries if not winners_store.contains(e["author_id"])]

    if not eligible:
        await results_channel.send("⚠️ Aucun gagnant éligible cette semaine (tous les participants ont déjà gagné auparavant).")
        try:
            await results_channel.send(f"📁 Fil des votes : {voting_thread.jump_url}")
        except Exception:
            pass
        try:
            await voting_thread.edit(archived=False, locked=True)
        except Exception:
            pass
        print("close_votes_and_announce_auto: no eligible winners")
        return

    max_votes = max(e["votes"] for e in eligible)
    winners = [e for e in eligible if e["votes"] == max_votes]

    if len(winners) == 1:
        w = winners[0]
        result = f"🏆 **Le gagnant de la semaine est {w['author_mention']} avec {max_votes} votes !**\n\nFélicitations ! Voici la photo gagnante :"
        await results_channel.send(result)
        await results_channel.send(embed=discord.Embed().set_image(url=w["image_url"]))
    else:
        authors = ", ".join(e["author_mention"] for e in winners)
        result = f"🏆 **Égalité avec {max_votes} votes chacun !**\n\nFélicitations à {authors} !\n\nVoici les photos gagnantes :"
        await results_channel.send(result)
        for e in winners:
            await results_channel.send(embed=discord.Embed().set_image(url=e["image_url"]))

    for e in winners:
        winners_store.add(e["author_id"])

    try:
        monthly_store.begin_new_week()
        for e in winners:
            monthly_store.add_weekly_winner(
                author_id=e["author_id"],
                author_mention=e["author_mention"],
                image_url=e["image_url"],
                votes=e["votes"]
            )
    except Exception as ex:
        print("Recording weekly winners failed:", ex)

    try:
        await results_channel.send(f"📁 Fil des votes : {voting_thread.jump_url}")
    except Exception:
        pass

    await asyncio.sleep(2)
    try:
        await voting_thread.edit(archived=False, locked=True)
    except Exception:
        pass

    print("close_votes_and_announce_auto: done")

    try:
        await maybe_open_monthly_contest()
    except Exception as ex:
        print("maybe_open_monthly_contest error:", ex)

@bot.tree.command(name="partage-photo", description="Ping les reporters pour partager leur photos")
async def share_photo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await send_partage_message_auto()
    await interaction.followup.send("Message envoyé dans le canal photo!", ephemeral=True)

@bot.tree.command(name="ouverture-des-votes", description="Ouvre la phase des votes")
async def open_votes(interaction: discord.Interaction):
    global last_photo_call
    await interaction.response.defer(ephemeral=True)

    if not last_photo_call:
        await interaction.followup.send("❌ Aucun appel à photos n'a été fait. Utilisez d'abord /partage-photo", ephemeral=True)
        return

    thread = await create_vote_thread_from_photos_auto()
    if thread is None:
        photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
        thread = await photo_channel.create_thread(
            name=f"📊 Votes - {datetime.now(tz).strftime('%d/%m/%Y')}",
            auto_archive_duration=1440
        )
        await thread.send("Aucune photo n'a été partagée depuis l'appel !")
        await interaction.followup.send("Fil créé, mais aucune photo trouvée", ephemeral=True)
        return

    await interaction.followup.send("Phase de votes ouverte !", ephemeral=True)

@bot.tree.command(name="fermeture-des-votes", description="Ferme les votes et annonce les résultats")
async def close_votes(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await close_votes_and_announce_auto()
    await interaction.followup.send("✅ Votes terminés et résultats annoncés !", ephemeral=True)

@bot.tree.command(name="fermeture-du-mensuel", description="Ferme le concours mensuel et annonce les résultats")
async def close_monthly(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    active = monthly_store.get_active()
    if not active or active.get("closed"):
        await interaction.followup.send("ℹ️ Aucun concours mensuel actif pour le moment.", ephemeral=True)
        return
    await close_monthly_contest_auto()
    await interaction.followup.send("✅ Concours mensuel clôturé et résultats annoncés !", ephemeral=True)

@bot.tree.command(name="winners-remove-weekly", description="Retire un utilisateur de la liste des gagnants hebdomadaires (réautorise à gagner la semaine)")
@app_commands.describe(user="Utilisateur à réautoriser pour les concours hebdomadaires")
async def winners_remove_weekly(interaction: discord.Interaction, user: discord.User):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Autorisation refusée. Administrateur requis.", ephemeral=True)
        return

    removed = winners_store.remove_weekly(user.id)
    if removed:
        await interaction.response.send_message(f"✅ {user.mention} a été retiré de la liste des gagnants hebdomadaires.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {user.mention} n'était pas dans la liste des gagnants hebdomadaires.", ephemeral=True)

@bot.tree.command(name="winners-remove-monthly", description="Retire un utilisateur de la liste des gagnants mensuels (réautorise à gagner le mensuel)")
@app_commands.describe(user="Utilisateur à réautoriser pour les concours mensuels")
async def winners_remove_monthly(interaction: discord.Interaction, user: discord.User):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Autorisation refusée. Administrateur requis.", ephemeral=True)
        return

    removed = winners_store.remove_monthly(user.id)
    if removed:
        await interaction.response.send_message(f"✅ {user.mention} a été retiré de la liste des gagnants mensuels.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {user.mention} n'était pas dans la liste des gagnants mensuels.", ephemeral=True)

def next_weekday_dt(now, target_weekday, hour, minute):
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate

async def scheduler_loop():
    await bot.wait_until_ready()
    print("Scheduler started. TIMEZONE =", TIMEZONE)
    while not bot.is_closed():
        now = datetime.now(tz)
        share_dt = next_weekday_dt(now, SHARE_WEEKDAY, SHARE_HOUR, SHARE_MIN)
        open_dt = next_weekday_dt(now, OPEN_WEEKDAY, OPEN_HOUR, OPEN_MIN)
        result_dt = next_weekday_dt(now, RESULT_WEEKDAY, RESULT_HOUR, RESULT_MIN)

        next_event_name, next_event_dt = min(
            [("share", share_dt), ("open", open_dt), ("result", result_dt)],
            key=lambda x: x[1]
        )

        wait_seconds = (next_event_dt - now).total_seconds()
        print(f"Next scheduled event: {next_event_name} at {next_event_dt.isoformat()} (in {int(wait_seconds)}s)")
        await asyncio.sleep(max(0, wait_seconds))

        try:
            if next_event_name == "share":
                await send_partage_message_auto()
            elif next_event_name == "open":
                await create_vote_thread_from_photos_auto()
            elif next_event_name == "result":
                await close_votes_and_announce_auto()
        except Exception as e:
            print("Scheduled event error:", e)

        await asyncio.sleep(1)

async def run_quick_test():
    await bot.wait_until_ready()
    await asyncio.sleep(1)
    print("TEST_MODE quick sequence starting")
    await send_partage_message_auto()
    await asyncio.sleep(TEST_WAIT_SEC)
    await create_vote_thread_from_photos_auto()
    await asyncio.sleep(TEST_WAIT_SEC)
    await close_votes_and_announce_auto()
    print("TEST_MODE quick sequence finished")

_original_on_ready = getattr(bot, "on_ready", None)

@bot.event
async def on_ready():
    if _original_on_ready:
        try:
            await _original_on_ready()
        except Exception:
            pass

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

    if TEST_MODE:
        bot.loop.create_task(run_quick_test())
    else:
        bot.loop.create_task(scheduler_loop())

    try:
        active = monthly_store.get_active()
        if active and not active.get("closed"):
            bot.loop.create_task(schedule_monthly_close())
    except Exception as ex:
        print("on_ready schedule_monthly_close error:", ex)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id == PHOTO_CHANNEL_ID:
        user_id = message.author.id
        if len(message.attachments) == 0:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    "❌ Les messages texte ne sont **pas autorisés** dans le canal photo.\n"
                    "Merci de ne poster que **des photos**."
                )
            except Exception:
                pass
            return

        if len(message.attachments) > 1:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    "❌ Vous ne pouvez poster qu'**une seule photo** par semaine.\n"
                    "Merci de ne partager qu'une seule image à la fois."
                )
            except Exception:
                pass
            return

        if user_submissions[user_id] >= 1:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    "❌ Vous avez déjà partagé une photo cette semaine.\n"
                    "Merci d'attendre la semaine prochaine pour en partager une nouvelle."
                )
            except Exception:
                pass
            return

        user_submissions[user_id] += 1

@bot.event
async def on_message_delete(message):
    try:
        if message.channel.id == PHOTO_CHANNEL_ID and len(message.attachments) > 0:
            user_id = message.author.id
            if user_id in user_submissions:
                user_submissions[user_id] = 0
    except Exception:
        pass

bot.run(TOKEN)