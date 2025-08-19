import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# Load variables from .env files
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
REPORTER_ROLE_ID = os.getenv("REPORTER_ROLE_ID")
REPORTER_BORDEAUX_ROLE_ID = os.getenv("REPORTER_BORDEAUX_ROLE_ID")
PHOTO_CHANNEL_ID = int(os.getenv("PHOTO_CHANNEL_ID"))

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
    
@bot.tree.command(name="partage_photo", description="Ping les reporters pour partager leur photos")
async def partage_photo(interaction: discord.Interaction):
        photo_channel = bot.get_channel(PHOTO_CHANNEL_ID)
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
        
# Run bot using the token fron .env
bot.run(TOKEN)