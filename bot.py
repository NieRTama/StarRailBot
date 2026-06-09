import asyncio
import logging
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=[], intents=intents)

@bot.event
async def on_ready():
    print(f"ログイン成功: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}")
    except Exception as e:
        print(f"同期エラー: {e}")

async def main():
    async with bot:
        await bot.load_extension("cogs.notify")
        await bot.load_extension("cogs.giftcode")
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot停止")
