import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load variables from .env files
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Set up bot
intents = discord.Intents.default()
intents.message_content = True # Allow to read messages
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def hello(ctx):
    await ctx.send("Hello!")

# Run bot using the token fron .env
bot.run(TOKEN)