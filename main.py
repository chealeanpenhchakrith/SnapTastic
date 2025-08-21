import os
import discord
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
VOTE_EMOJI = os.getenv("VOTE_EMOJI", "🗳️")

user_submissions = defaultdict(int) # Track number of photos per user
last_photo_call = None # Track when /partage-photo was last run

# Set up bot
intents = discord.Intents.default()
intents.message_content = True # Allow to read messages
intents.guilds = True
bot = commands.Bot(command_prefix="/", intents=intents)

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

@bot.tree.command(name="partage_photo", description="Ping les reporters pour partager leur photos")
async def partage_photo(interaction: discord.Interaction):
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
# Run bot using the token fron .env
bot.run(TOKEN)