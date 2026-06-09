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

GAME8_URL = "https://game8.jp/houkaistarrail/525554"
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
DATE_FMT = "%Y/%m/%d %H:%M"
# game8 形式: 【開催期間】 M/DD HH:MM 〜M/DD HH:MM
PERIOD_RE = re.compile(
    r"【開催期間】\s*(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})\s*[〜~]\s*(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})"
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


def _add_year(raw: str) -> datetime.datetime:
    """M/D HH:MM 形式に年を付与して返す。30日以上過去なら翌年扱い"""
    now = datetime.datetime.now()
    dt = datetime.datetime.strptime(f"{now.year}/{raw.strip()}", "%Y/%m/%d %H:%M")
    if dt < now - datetime.timedelta(days=30):
        dt = dt.replace(year=now.year + 1)
    return dt


def _fetch_events() -> list:
    """game8から開催中のイベントを取得する"""
    try:
        res = requests.get(GAME8_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        res.encoding = "utf-8"
    except requests.RequestException as e:
        log.error("イベントページ取得失敗: %s", e)
        return []

    soup = BeautifulSoup(res.text, "html.parser")

    heading = soup.find(
        lambda tag: tag.name in ("h2", "h3", "h4") and "開催中のイベント" in tag.get_text()
    )
    if heading is None:
        log.warning("「開催中のイベント」セクションが見つかりませんでした")
        return []

    table = heading.find_next("table")
    if table is None:
        log.warning("イベントテーブルが見つかりませんでした")
        return []

    events = []
    seen_names = set()

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        # イベント名: 最初のセル内のリンクテキスト（画像のみの場合はalt属性）
        name_cell = cells[0]
        link = name_cell.find("a")
        if link:
            name = link.get_text(strip=True)
            if not name:
                img = link.find("img")
                name = img.get("alt", "").strip() if img else ""
        else:
            name = name_cell.get_text(strip=True)

        if not name or name in seen_names:
            continue

        # 全セルから【開催期間】パターンを検索
        period_text = " ".join(c.get_text(" ", strip=True) for c in cells)
        match = PERIOD_RE.search(period_text)
        if not match:
            continue

        try:
            start_dt = _add_year(match.group(1))
            end_dt = _add_year(match.group(2))
        except ValueError:
            continue

        if end_dt < datetime.datetime.now():
            continue

        seen_names.add(name)
        events.append({
            "name": name,
            "start": start_dt.strftime(DATE_FMT),
            "end": end_dt.strftime(DATE_FMT),
            "start_dt": start_dt,
        })

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
