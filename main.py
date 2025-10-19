import os
import discord
import asyncio
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timezone
import re
import json

# Load variables from .env files
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
REPORTER_ROLE_ID = os.getenv("REPORTER_ROLE_ID")
REPORTER_BORDEAUX_ROLE_ID = os.getenv("REPORTER_BORDEAUX_ROLE_ID")
PHOTO_CHANNEL_ID = int(os.getenv("PHOTO_CHANNEL_ID"))
PHOTO_RESULT_CHANNEL_ID = int(os.getenv("PHOTO_RESULT_CHANNEL_ID"))
VOTE_EMOJI = os.getenv("VOTE_EMOJI", "🗳️")

user_submissions = defaultdict(int) # Track number of photos per user
last_photo_call = None # Track when /partage-photo was last run

# Set up bot
intents = discord.Intents.default()
intents.message_content = True # Allow to read messages
intents.guilds = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)




# --- Track user votes per voting thread ---
user_votes_per_thread = defaultdict(dict)  # {thread_id: {user_id: message_id}}
# Restrict users to one vote per voting thread
@bot.event
async def on_reaction_add(reaction, user):
    # Ignore bot's own reactions
    if user == bot.user:
        return
    # Only process vote emoji in threads named "📊 Votes"
    message = reaction.message
    thread = message.channel
    if not isinstance(thread, discord.Thread):
        return
    if not thread.name.startswith("📊 Votes"):
        return
    if str(reaction.emoji) != VOTE_EMOJI:
        return
    # Track votes per user per thread
    thread_id = thread.id
    user_id = user.id
    # If user already voted for another message, remove this reaction
    voted_msg_id = user_votes_per_thread[thread_id].get(user_id)
    if voted_msg_id is not None and voted_msg_id != message.id:
        await reaction.remove(user)
        try:
            await user.send("⚠️ Vous ne pouvez voter que pour une seule photo ⚠️")
        except Exception:
            pass
        return
    # If this is user's first vote, record it
    user_votes_per_thread[thread_id][user_id] = message.id


# Allow users to change their vote by handling reaction removal
@bot.event
async def on_reaction_remove(reaction, user):
    # Ignore bot's own reactions
    if user == bot.user:
        return
    message = reaction.message
    thread = message.channel
    if not isinstance(thread, discord.Thread):
        return
    if not thread.name.startswith("📊 Votes"):
        return
    if str(reaction.emoji) != VOTE_EMOJI:
        return
    thread_id = thread.id
    user_id = user.id
    # If user unvoted their tracked message, remove their vote record
    if user_votes_per_thread[thread_id].get(user_id) == message.id:
        del user_votes_per_thread[thread_id][user_id]
        
        
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@bot.event
async def on_message(message):
    # ignore bot's own messages
    if message.author == bot.user:
        return
    # Check if message is in photo channel
    if message.channel.id == PHOTO_CHANNEL_ID:
        user_id = message.author.id
        
        # If messages has no images (only text)
        if len(message.attachments) == 0:
            await message.delete()
            await message.author.send(
                "⚠️ Les messages texte ne sont **pas autorisés** dans le canal photo ⚠️\n"
                "✅ Merci de ne poster qu'une seule **photo** durant la phase de partage photo ✅"
            )
            return

        # If messages has more than 1 image
        # if len(message.attachments) > 1:
        #     await message.delete()
        #     await message.author.send(
        #         "⚠️ Vous ne pouvez poster qu'**une seule photo** par semaine, si vous souhaitez remplacer votre photo déjà postée, vous pouvez supprimer et reposter tant que cela reste une seule photo de votre part ⚠️\n"
        #         "✅ Merci de ne partager qu'une seule image à la fois ✅"
        #     )
        
        if user_submissions[user_id] >= 1:
            await message.delete()
            await message.author.send(
                "⚠️ Vous avez déjà partagé une photo cette semaine, si vous souhaitez remplacer votre photo déjà postée, vous pouvez supprimer et reposter tant que cela reste une seule photo de votre part ⚠️\n"
                "✅ Merci d'attendre la semaine prochaine pour en partager une nouvelle ✅"
            )
            return
        
        user_submissions[user_id] += 1

@bot.event
async def on_message_delete(message):
    # If deleted message was in photo channel and had an image
    if message.channel.id == PHOTO_CHANNEL_ID and len(message.attachments) > 0:
        user_id = message.author.id
        # Reset user's submission count
        if user_id in user_submissions:
            user_submissions[user_id] = 0

@bot.tree.command(name="partage-photo", description="Ping les reporters pour partager leur photos")
async def share_photo(interaction: discord.Interaction):
        global last_photo_call
        photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
        last_photo_call = datetime.now(timezone.utc)
        message = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

Une **nouvelle semaine** commence ✨ 
C'est le moment idéal pour partager vos plus belles photos dans ce canal 📸

**__Rappel des règles__** :

• Un gagnant hebdomadaire ne peut pas regagner une autre semaine du même mois, pour laisser la chance aux autres
• Vous pouvez poster **1 seule photo** jusqu'au vendredi
• Merci de ne pas écrire de texte dans ce canal (photo uniquement)
• Les votes auront lieu de **samedi** au **dimanche 18h**
• Le ou la gagnant(e) sera annoncé(e) **dimanche soir** 🏆

Bonne chance à toutes et à tous, et amusez-vous bien 🎉"""
        
        # Send message to photo channel
        await photo_channel.send(
            content=message,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )
        
        # Confirm to user who ran the command
        await interaction.response.send_message(
            "Message envoyé dans le canal photo!", 
            ephemeral=True
        )
@bot.tree.command(name="remove-weekly-winner", description="Retire un membre de la liste des gagnants hebdomadaires")
@app_commands.describe(user="Sélectionnez le membre à retirer des gagnants")
async def remove_weekly_winner(interaction: discord.Interaction, user: discord.Member):
    user_id = user.id
    json_path = os.path.join(os.path.dirname(__file__), "weekly-winner.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        await interaction.response.send_message("Impossible de lire le fichier weekly-winner.json.", ephemeral=True)
        return
    original_len = len(data)
    # Remove any entry where user_id is in winner_ids
    data = [entry for entry in data if user_id not in entry.get("winner_ids", [])]
    removed = len(data) < original_len
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if removed:
        await interaction.response.send_message(f"L'objet contenant '{user.display_name}' a été supprimé de la liste des gagnants hebdomadaires.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Aucun objet trouvé pour '{user.display_name}' dans la liste des gagnants.", ephemeral=True)


@bot.tree.command(name="liste-gagnants", description="Affiche la liste des gagnants hebdomadaires")
async def list_winners(interaction: discord.Interaction):
    """Affiche le contenu de weekly-winner.json de façon lisible.
    Le résultat est envoyé en message éphemère. Si le contenu est trop long, envoie un fichier.
    """
    json_path = os.path.join(os.path.dirname(__file__), "weekly-winner.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        await interaction.response.send_message("Impossible de lire weekly-winner.json.", ephemeral=True)
        return

    if not data:
        await interaction.response.send_message("Aucun gagnant enregistré.", ephemeral=True)
        return

    lines = ["**Liste des gagnants hebdomadaires :**"]
    for entry in data:
        date = entry.get("date", "?")
        ids = entry.get("winner_ids", [])
        if not ids:
            lines.append(f"{date}: Aucun gagnant")
            continue
        parts = []
        for uid in ids:
            try:
                member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            except Exception:
                member = None
            if member:
                parts.append(member.display_name)
            else:
                parts.append(f"<@{uid}>")
        lines.append(f"{date}: " + ", ".join(parts))

    content = "\n".join(lines)

    # If content too long for a discord message, send as file
    if len(content) > 1900:
        import io
        buf = io.BytesIO(content.encode('utf-8'))
        await interaction.response.send_message("La liste est trop longue, je l'envoie en fichier.", file=discord.File(buf, filename="weekly-winner-list.txt"), ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)

@bot.tree.command(name="ouverture-des-votes", description="Ouvre la phase des votes")
async def open_votes(interaction: discord.Interaction):
    global last_photo_call
    if not last_photo_call:
        await interaction.response.send_message(
            "⚠️ Aucun appel à photos n'a été fait. Utilisez d'abord /partage-photo ⚠️",
            ephemeral=True
        )
        return

    # Acknowledge the interaction immediately because we do multiple
    # long-running API calls (creating threads, iterating history, adding reactions).
    # Deferring gives us more time and lets us use followup.send(...) later.
    await interaction.response.defer(ephemeral=True)

    photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
    thread = await photo_channel.create_thread(
        name=f"📊 Votes - {datetime.now().strftime('%d/%m/%Y')}",
        auto_archive_duration=1440
    )
    
    messages = []
    async for message in photo_channel.history(limit=100):
        if message.created_at < last_photo_call:
            break
        if message.attachments:
            messages.append(message)
    
    if not messages:
        await thread.send("Aucune photo n'a été partagée depuis l'appel !")
        await interaction.followup.send("Fil créé, mais aucune photo trouvée", ephemeral=True)
        return
    
    intro = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

**La phase de votes est ouverte !**

Pour voter, réagissez avec {VOTE_EMOJI} sur votre photo préférée de cette semaine.

**__Rappel des règles__** :

• Ne pas ajouter de photos durant le vote, sinon elle sera supprimée
• Vous pouvez voter pour une seule photo
• Les votes sont ouverts jusqu'à dimanche 18h
• Le/la gagnant(e) sera annoncé(e) dimanche soir

**📸 __Voici les photos soumises :__**
⠀"""

    await thread.send(intro)
    for msg in reversed(messages):
        # Modified - URL should display cleanly in Discord without filename
        photo_message = await thread.send(
        content=f"Photo de {msg.author.mention}:",
        embed=discord.Embed().set_image(url=msg.attachments[0].url)
        )
        await photo_message.add_reaction(VOTE_EMOJI)
    
    # Reset for next week
    user_submissions.clear()
    last_photo_call = None
    
    await interaction.followup.send("Phase de votes ouverte !", ephemeral=True)

import json

@bot.tree.command(name="fermeture-des-votes", description="Ferme les votes et annonce les résultats")
async def close_votes(interaction: discord.Interaction):
    try:
        # Defer response immediately
        await interaction.response.defer(ephemeral=True)
        
        # Get channels
        photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
        results_channel = bot.get_channel(PHOTO_RESULT_CHANNEL_ID)
        guild = interaction.guild
        
        # Fetch active threads
        active_threads = await guild.active_threads()
        voting_thread = None
        
        # Find voting thread from photo channel
        for thread in active_threads:
            if thread.parent_id == PHOTO_CHANNEL_ID and thread.name.startswith("📊 Votes"):
                voting_thread = thread
                break
        
        if not voting_thread:
            await interaction.followup.send(
                "❌ Aucun fil de vote actif trouvé.",
                ephemeral=True
            )
            return
        
        # Cache image URLs and collect votes. Store numeric author IDs for reliability.
        vote_counts = {}  # {message_id: {votes, author_id, image_url}}
        cached_images = {}

        async for message in voting_thread.history(limit=None):
            if message.embeds and len(message.embeds) > 0:
                # Try to get the author ID from mentions first (most reliable),
                # then fall back to regex extraction from the content.
                author_id = None
                if message.mentions:
                    try:
                        author_id = message.mentions[0].id
                    except Exception:
                        author_id = None
                if author_id is None:
                    m = re.search(r"<@!?(?P<id>\d+)>", message.content)
                    if m:
                        try:
                            author_id = int(m.group("id"))
                        except Exception:
                            author_id = None
                # As a last resort, try to parse any digits after 'Photo de '
                if author_id is None:
                    try:
                        mention_part = message.content.split("Photo de ")[1].rstrip(":")
                        digits = re.search(r"(\d+)", mention_part)
                        if digits:
                            author_id = int(digits.group(1))
                    except Exception:
                        author_id = None

                cached_images[message.id] = message.embeds[0].image.url

                for reaction in message.reactions:
                    if str(reaction.emoji) == VOTE_EMOJI:
                        vote_counts[message.id] = {
                            'votes': max(0, reaction.count - 1),
                            'author_id': author_id,
                            'image_url': cached_images[message.id]
                        }
                        print(f"Found photo by {author_id} with {reaction.count - 1} votes")
                        break
        
        if not vote_counts:
            await interaction.followup.send("❌ Aucun vote n'a été trouvé.", ephemeral=True)
            return
        
        # Load previous winner IDs
        json_path = os.path.join(os.path.dirname(__file__), "weekly-winner.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                previous_data = json.load(f)
        except Exception:
            previous_data = []
        previous_winner_ids = set()
        for entry in previous_data:
            previous_winner_ids.update(entry.get("winner_ids", []))

        # Find winner(s) by ignoring previous winners entirely when computing top votes.
        # Build a dict of eligible candidates (authors who have NOT previously won).
        eligible_vote_counts = {
            msg_id: data
            for msg_id, data in vote_counts.items()
            if data.get('author_id') is not None and data.get('author_id') not in previous_winner_ids
        }

        eligible_winners = []
        if eligible_vote_counts:
            # Compute max among eligible candidates only
            max_votes = max(data['votes'] for data in eligible_vote_counts.values())
            for msg_id, data in eligible_vote_counts.items():
                if data['votes'] == max_votes:
                    eligible_winners.append((msg_id, data, data['author_id']))
        else:
            # No eligible candidates (all submitters already won previously)
            eligible_winners = []

        # Format results message
        if not eligible_winners:
            result = "❌ Aucun gagnant éligible cette semaine (tous les top-votés ont déjà gagné auparavant). Rappel : un gagnant hebdomadaire ne peut pas regagner d'autres concours hebdomadaires durant le mois."
            await results_channel.send(result)
            await interaction.followup.send(
                "Votes terminés, mais aucun nouveau gagnant possible !",
                ephemeral=True
            )
            # Archive thread
            await asyncio.sleep(3)
            await voting_thread.edit(archived=True, locked=True)
            return

        if len(eligible_winners) == 1:
            _, winner_data, winner_id = eligible_winners[0]
            result = f"""🏅 Nouveau Gagnant !
La semaine passée, avec {max_votes} vote(s), notre gagnant(e) est ** <@{winner_id}> avec sa superbe photo !**

**Voici la photo gagnante** :

"""
        else:
            authors = ", ".join(f"<@{winner_id}>" for _, _, winner_id in eligible_winners)
            result = f"""🏅 Nouveaux Gagnants !
La semaine passée, avec {max_votes} votes, nos gagnant(e)s sont ** {authors} avec leurs superbes photos !**
🏆 **Nous avons une égalité avec {max_votes} votes chacun !**

Voici les photos gagnantes :

"""

        # Send results
        await results_channel.send(result)

        # Send winning photos using cached URLs
        for msg, data, _ in eligible_winners:
            embed = discord.Embed().set_image(url=data['image_url'])
            await results_channel.send(embed=embed)

        # Store winner user IDs in weekly-winner.json
        winner_ids = [winner_id for _, _, winner_id in eligible_winners]
        week_entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "winner_ids": winner_ids
        }
        previous_data.append(week_entry)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(previous_data, f, ensure_ascii=False, indent=2)

        # Wait for content to be processed
        await asyncio.sleep(3)

        # Do not archive or lock the thread; keep it visible for users
        await results_channel.send(f"""**Voir le fil des votes ici : ** <#{voting_thread.id}>
                                   
✨ N'hésitez pas à nous proposer vos photographies !
Au-delà du petit concours, c'est surtout pour se partager nos photos à toutes et découvrir de nouveaux styles, de nouvelles manières de faire ! Et ce peu importe votre niveau 😄

ℹ️ Comment participer
Tout se passe dans  <#{895630276787576832}> ! Postez vos photos et attendez les votes !

👉 Nouvelle semaine !
La prochaine vague de photos peut être envoyée jusqu'à samedi non inclus !
                                   """)
        await interaction.followup.send(
            "✅ Votes terminés et résultats annoncés !",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error in close_votes: {e}")
        await interaction.followup.send(
            "❌ Une erreur s'est produite lors de la fermeture des votes.",
            ephemeral=True
        )
# Run bot using the token fron .env
bot.run(TOKEN)