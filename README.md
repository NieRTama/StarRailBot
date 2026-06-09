# StarRailBot

崩壊：スターレイルプレイヤー向け Discord Bot。  
イベント自動通知とギフトコード自動検出の2機能を搭載しています。

---

## 機能

### 1. イベント自動通知

wikiwiki.jp のイベントページを3時間ごとに監視し、**限定イベントのみ**を通知します。

**通知の種類:**
- 新規イベント開始の検出・通知
- イベント終了3日前の警告
- 終了済みイベントの自動削除

**月次リマインダー（毎日 5:00）:**
- 毎月1日：月替わりチケット交換可能
- 毎月16日：混沌の記憶・末日の幻影・純虚の劇場の切替

**@everyone 監視：** 通知チャンネルへの @everyone メンションに対し、開催中のイベント一覧を自動返信します。

> **注意：** 2026/6/1 以前に開始したイベントは初回起動時に通知されません（既存イベントの通知スキップ）。

---

### 2. ギフトコード自動検出

GameWith のコード一覧ページを3時間ごとに監視し、新しいコードを検出すると通知します。  
`known_codes.json` で既検出コードを管理し、重複通知を防ぎます。

**通知内容:** コード文字列と HoyoVerse 公式受取リンク（`hsr.hoyoverse.com/gift`）

---

## セットアップ

### 必要環境

- Python 3.10 以上
- Discord Bot トークン（[Discord Developer Portal](https://discord.com/developers/applications)）

### インストール

```bash
git clone https://github.com/NieRTama/StarRailBot.git
cd StarRailBot
pip install -r requirements.txt
```

### 環境変数の設定

`.env.example` をコピーして `.env` を作成し、各値を入力します。

```bash
cp .env.example .env
```

```env
DISCORD_TOKEN=your_discord_token_here
NOTIFY_CHANNEL_ID=123456789012345678
GIFTCODE_CHANNEL_ID=123456789012345678
```

| 変数名 | 説明 |
|--------|------|
| `DISCORD_TOKEN` | Discord Bot のトークン |
| `NOTIFY_CHANNEL_ID` | イベント通知・@everyone 監視チャンネルの ID |
| `GIFTCODE_CHANNEL_ID` | ギフトコード通知チャンネルの ID |

### 起動

```bash
python bot.py
```

---

## ファイル構成

```
StarRailBot/
├── bot.py                  # メイン起動ファイル
├── .env                    # 環境変数（Git 管理外）
├── .env.example            # 設定テンプレート
├── requirements.txt
├── cogs/
│   ├── notify.py           # イベント通知
│   └── giftcode.py         # ギフトコード検出
└── data/                   # 実行時自動生成
    ├── events.json         # 検出済みイベント記録
    └── known_codes.json    # 検出済みコード記録
```

---

## 注意事項

- 通知タイミングは wikiwiki.jp および GameWith の更新頻度に依存します
- `data/` 内の JSON ファイルを削除すると、次回起動時に全件通知が再発生します
- 大文字小文字混在のコード（例：`SitByEvanescia`）にも対応しています
