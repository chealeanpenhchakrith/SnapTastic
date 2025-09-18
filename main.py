import os
import discord
import asyncio
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timezone

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
            await user.send("❌ Vous ne pouvez voter que pour une seule photo !")
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
                "❌ Les messages texte ne sont **pas autorisés** dans le canal photo.\n"
                "Merci de ne poster que **des photos**."
            )
            return

        # If messages has more than 1 image
        if len(message.attachments) > 1:
            await message.delete()
            await message.author.send(
                "❌ Vous ne pouvez poster qu'**une seule photo** par semaine.\n"
                "Merci de ne partager qu'une seule image à la fois."
            )
        
        if user_submissions[user_id] >= 1:
            await message.delete()
            await message.author.send(
                "❌ Vous avez déjà partagé une photo cette semaine.\n"
                "Merci d'attendre la semaine prochaine pour en partager une nouvelle."
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

• Vous pouvez poster **1 seule photo** jusqu'à samedi 00:00
• Merci de ne pas écrire de texte dans ce canal (photo uniquement)
• Les votes auront lieu de **samedi 00:00** à **dimanche 18:00** 🗳️
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

@bot.tree.command(name="ouverture-des-votes", description="Ouvre la phase des votes")
async def open_votes(interaction: discord.Interaction):
    global last_photo_call
    if not last_photo_call:
        await interaction.response.send_message(
            "❌ Aucun appel à photos n'a été fait. Utilisez d'abord /partage-photo",
            ephemeral=True
        )
        return

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
        await interaction.response.send_message("Fil créé, mais aucune photo trouvée", ephemeral=True)
        return
    
    intro = f"""Bonjour <@&{REPORTER_ROLE_ID}> <@&{REPORTER_BORDEAUX_ROLE_ID}> !

**🗳️ La phase de votes est ouverte !**

Pour voter, réagissez avec {VOTE_EMOJI} sur vos photos préférées.

• Vous pouvez voter pour plusieurs photos
• Les votes sont ouverts jusqu'à dimanche 18h00
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
    
    await interaction.response.send_message("Phase de votes ouverte !", ephemeral=True)

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
        
        # Cache image URLs and collect votes
        vote_counts = {}
        cached_images = {}
        
        async for message in voting_thread.history(limit=None):
            if message.embeds and len(message.embeds) > 0:
                author = message.content.split("Photo de ")[1].rstrip(":")
                cached_images[message.id] = message.embeds[0].image.url
                
                for reaction in message.reactions:
                    if str(reaction.emoji) == VOTE_EMOJI:
                        vote_counts[message] = {
                            'votes': reaction.count - 1,
                            'author': author,
                            'image_url': cached_images[message.id]
                        }
                        print(f"Found photo by {author} with {reaction.count - 1} votes")
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

        # Find winner(s) excluding previous winners
        max_votes = max(data['votes'] for data in vote_counts.values())
        eligible_winners = []
        for msg, data in vote_counts.items():
            # Extract user ID from mention string
            try:
                mention = msg.content.split("Photo de ")[1].rstrip(":")
                if mention.startswith("<@") and mention.endswith(">"):
                    user_id = int(mention.replace("<@","").replace(">","").strip())
                    if data['votes'] == max_votes and user_id not in previous_winner_ids:
                        eligible_winners.append((msg, data, user_id))
            except Exception:
                pass

        # Format results message
        if not eligible_winners:
            result = "❌ Aucun gagnant éligible cette semaine (tous les top-votés ont déjà gagné auparavant)."
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
            result = f"""🏆 **Le gagnant de la semaine est <@{winner_id}> avec {max_votes} votes !**

Félicitations ! Voici la photo gagnante :"""
        else:
            authors = ", ".join(f"<@{winner_id}>" for _, _, winner_id in eligible_winners)
            result = f"""🏆 **Nous avons une égalité avec {max_votes} votes chacun !**
            
Félicitations à {authors} !

Voici les photos gagnantes :"""

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
        await results_channel.send(f"🔗 **Voir le fil des votes ici :** <#{voting_thread.id}>")
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