import asyncio
import datetime
import json
import logging
import os
import re
import discord
import requests
from bs4 import BeautifulSoup
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

WIKI_URL = "https://wikiwiki.jp/star-rail/%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "0"))
DATE_FMT = "%Y/%m/%d"
PERIOD_RE = re.compile(
    r"(\d{4}/\d{2}/\d{2})\s*[~〜]\s*(\d{4}/\d{2}/\d{2})"
)
MIN_NOTIFY_DATE = datetime.datetime(2026, 6, 1)


def _load_events() -> dict:
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_events(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fetch_events() -> list:
    """wikiwikiから限定イベントを取得する"""
    try:
        res = requests.get(WIKI_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        res.encoding = "utf-8"
    except requests.RequestException as e:
        log.error("イベントページ取得失敗: %s", e)
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    events = []
    seen_names = set()
    in_limited_section = False

    all_elements = soup.find_all(["h2", "h3", "h4", "h5", "table"])

    for elem in all_elements:
        if elem.name in ("h2", "h3", "h4", "h5"):
            text = elem.get_text(strip=True)
            if "限定イベント" in text:
                in_limited_section = True
            elif in_limited_section:
                # 同レベル以上の別セクションに入ったらリセット
                in_limited_section = False
            continue

        if elem.name != "table" or not in_limited_section:
            continue

        header_row = elem.find("tr")
        if not header_row:
            continue

        headers = header_row.find_all(["th", "td"])
        name_col = next(
            (i for i, h in enumerate(headers) if "イベント名" in h.get_text()), None
        )
        period_col = next(
            (i for i, h in enumerate(headers) if "開催期間" in h.get_text()), None
        )

        if name_col is None or period_col is None:
            continue

        for row in elem.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(name_col, period_col):
                continue

            period_text = cells[period_col].get_text(strip=True)
            match = PERIOD_RE.search(period_text)
            if not match:
                continue

            start_str = match.group(1).strip()
            end_str = match.group(2).strip()

            name_cell = cells[name_col]
            link = name_cell.find("a")
            name = link.get_text(strip=True) if link else name_cell.get_text(strip=True)

            if not name or name in seen_names:
                continue

            try:
                end_dt = datetime.datetime.strptime(end_str, DATE_FMT)
                start_dt = datetime.datetime.strptime(start_str, DATE_FMT)
            except ValueError:
                continue

            if end_dt < datetime.datetime.now():
                continue

            seen_names.add(name)
            events.append({"name": name, "start": start_str, "end": end_str, "start_dt": start_dt})

    log.info("%d 件のイベントを検出: %s", len(events), [e["name"] for e in events])
    return events


class NotifyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.event_check.start()
        self.monthly_task.start()

    def cog_unload(self):
        self.event_check.cancel()
        self.monthly_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if NOTIFY_CHANNEL_ID == 0 or message.channel.id != NOTIFY_CHANNEL_ID:
            return

        if not message.mention_everyone:
            return

        try:
            now = datetime.datetime.now()
            events = _load_events()

            active = [
                ev for ev in events.values()
                if datetime.datetime.strptime(ev["start"], DATE_FMT) <= now
                <= datetime.datetime.strptime(ev["end"], DATE_FMT)
            ]

            for ev in active:
                await message.channel.send(
                    f'イベントあり：**{ev["name"]}**（〜{ev["end"]}）'
                )
        except Exception as e:
            log.error("on_messageエラー: %s", e)

    @tasks.loop(hours=3)
    async def event_check(self):
        if NOTIFY_CHANNEL_ID == 0:
            return

        channel = self.bot.get_channel(NOTIFY_CHANNEL_ID)
        if channel is None:
            return

        now = datetime.datetime.now()
        events = _load_events()
        fetched = await asyncio.to_thread(_fetch_events)
        changed = False

        expired = [
            name for name, ev in events.items()
            if datetime.datetime.strptime(ev["end"], DATE_FMT) < now
        ]

        for name in expired:
            del events[name]
            changed = True
            log.info("イベント終了・削除: %s", name)

        for ev in fetched:
            name = ev["name"]
            if name in events:
                continue

            start_dt = ev.pop("start_dt")
            events[name] = {
                "name": name,
                "start": ev["start"],
                "end": ev["end"],
                "notified_3days": False,
            }
            changed = True

            # 2026/6/1以前に開始したイベントは通知しない（既存イベントの初回スキップ）
            if start_dt < MIN_NOTIFY_DATE:
                log.info("既存イベントのため通知スキップ: %s", name)
                continue

            embed = discord.Embed(
                title="🎉 新しいイベントが始まりました！",
                color=discord.Color.gold(),
            )
            embed.add_field(name="イベント名", value=name, inline=False)
            embed.add_field(name="開催期間", value=f"{ev['start']} 〜 {ev['end']}", inline=False)
            embed.set_footer(text="崩壊：スターレイル")
            await channel.send(embed=embed)
            log.info("新規イベント通知: %s", name)

        for name, ev in events.items():
            if ev.get("notified_3days"):
                continue

            end_dt = datetime.datetime.strptime(ev["end"], DATE_FMT)
            days_left = (end_dt - now).total_seconds() / 86400

            if 0 <= days_left <= 3:
                embed = discord.Embed(
                    title="⏰ イベント終了3日前です",
                    color=discord.Color.orange(),
                )
                embed.add_field(name="イベント名", value=name, inline=False)
                embed.add_field(name="終了日", value=ev["end"], inline=False)
                embed.set_footer(text="崩壊：スターレイル")
                await channel.send(embed=embed)
                events[name]["notified_3days"] = True
                changed = True
                log.info("3日前通知: %s", name)

        if changed:
            _save_events(events)

    @event_check.before_loop
    async def before_event_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def monthly_task(self):
        if NOTIFY_CHANNEL_ID == 0:
            return

        now = datetime.datetime.now()
        if now.hour != 5 or now.minute != 0:
            return

        channel = self.bot.get_channel(NOTIFY_CHANNEL_ID)
        if channel is None:
            return

        try:
            if now.day == 1:
                await channel.send("月初めチケット交換可能です")
            elif now.day == 16:
                await channel.send("混沌の記憶・末日の幻影・純虚の劇場の切替が近いです")
        except Exception as e:
            log.error("通知エラー: %s", e)

    @monthly_task.before_loop
    async def before_monthly_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(NotifyCog(bot))
