import asyncio
import json
import logging
import os
import re
import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

GAMEWITH_URL = "https://gamewith.jp/houkaistarrail/article/show/396232"
GIFT_BASE_URL = "https://hsr.hoyoverse.com/gift?code="
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
KNOWN_CODES_FILE = os.path.join(DATA_DIR, "known_codes.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 大文字小文字混在のコードに対応（SitByEvanescia、SilverWolfLV999 など）
CODE_PATTERN = re.compile(r'\b([A-Za-z][A-Za-z0-9]{4,19})\b')
EXCLUDE_CODES = {
    "JAVASCRIPT", "STYLESHEET", "GOOGLETAGMANAGER", "CLOUDFLARE",
    "ADDEVENTLISTENER", "STARRAIL", "HOYOVERSE", "GAMEWITH",
}
GIFTCODE_CHANNEL_ID = int(os.getenv("GIFTCODE_CHANNEL_ID", "0"))


def _load_known_codes() -> set:
    if os.path.exists(KNOWN_CODES_FILE):
        with open(KNOWN_CODES_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def _save_known_codes(codes: set):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KNOWN_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(codes), f, ensure_ascii=False, indent=2)


def _fetch_codes() -> list:
    try:
        res = requests.get(GAMEWITH_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        res.encoding = "utf-8"
    except requests.RequestException as e:
        log.error("ページ取得失敗: %s", e)
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    codes: set = set()

    # gift?code= リンクからコード抽出（大文字小文字混在コードを正確に取得）
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "gift?code=" in href:
            code = href.split("code=")[-1].strip()
            if code:
                codes.add(code)

    # code/strong/b/td/span タグ内のコード候補を抽出
    for tag in soup.find_all(["code", "strong", "b", "td", "span"]):
        text = tag.get_text(strip=True)
        if CODE_PATTERN.fullmatch(text) and text.upper() not in EXCLUDE_CODES:
            codes.add(text)

    # ページ全体からコード候補を抽出
    for match in CODE_PATTERN.findall(soup.get_text()):
        if match.upper() not in EXCLUDE_CODES:
            codes.add(match)

    log.info("%d 件のコード候補を検出", len(codes))
    return list(codes)


class GiftCodeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giftcode_check.start()

    def cog_unload(self):
        self.giftcode_check.cancel()

    @tasks.loop(hours=3)
    async def giftcode_check(self):
        if GIFTCODE_CHANNEL_ID == 0:
            return

        channel = self.bot.get_channel(GIFTCODE_CHANNEL_ID)
        if channel is None:
            return

        known = _load_known_codes()
        found = await asyncio.to_thread(_fetch_codes)
        new_codes = [c for c in found if c not in known]

        if not new_codes:
            log.info("新しいコードはありませんでした。")
            return

        log.info("新しいコードが %d 件見つかりました！", len(new_codes))

        for code in new_codes:
            gift_url = f"{GIFT_BASE_URL}{code}"
            embed = discord.Embed(
                title="🎁 崩壊：スターレイル 新しいギフトコードを発見！",
                color=0x9B59B6,
            )
            embed.add_field(name="コード", value=f"`{code}`", inline=True)
            embed.add_field(
                name="受け取りリンク",
                value=f"[👉 クリックして受け取る]({gift_url})",
                inline=True,
            )
            embed.set_footer(text="GameWithから自動検出 | StarRailBot")
            await channel.send(content="@here 新しいコードが見つかりました！", embed=embed)

        known.update(new_codes)
        _save_known_codes(known)

    @giftcode_check.before_loop
    async def before_giftcode_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(GiftCodeCog(bot))
