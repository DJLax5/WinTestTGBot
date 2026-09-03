# WinTestTGBot - notes for AI assisted development

Telegram bot that bridges the chat of the Win-Test contest logger (UDP broadcast
protocol on the station LAN) with Telegram private and group chats. Written by
DJLax5 (Fabian). The skeleton and working principle are human written; AI is used
for bug fixing, pen testing and hardening only.

## Repository rules

- NEVER commit or push to `main`. Active contest stations pull `main` directly.
- Work on feature branches. Merge requests into `main` are done by the owner.
- `dev` is the integration branch for new features (see README).
- Backwards compatibility is mandatory: after a `git pull` on `main` the bot must
  run with the existing `.env`, existing `data/wttgbot.json` and the already
  installed packages. No new pip packages, no new mandatory `.env` keys (new keys
  must have a default via `os.getenv(key, default)`), no database migrations that
  cannot be handled by `checkDatabase()` in `BOTConfiguration.py`.
- `requirements.txt` is unpinned. Stations may run any `python-telegram-bot` >= 20.
  Only use PTB API that exists since 20.0 (`Application`, `filters`, `telegram.error.*`).
- Python 3.11 is the tested interpreter. The stations run Windows (`start.bat`).
  Keep Linux working too (test environment).

## Code style

- Integrate with the existing style: one class per module, `cf.log` for logging
  with a `[TAG]` prefix (`[BOT]`, `[WT]`, `[TCM]`, `[CONFIG]`, `[ML]`, `[TLH]`).
- Efficient code, few comments. Inline comments only where the logic is not obvious.
- ASCII only in code. Non-ASCII text belongs into `lang/*.json`.
- No emoji in code. No cosmetic whitespace alignment.
- User facing strings go into `lang/en.json` and `lang/de.json` (same keys, same
  `[placeholders]`). `MulitLanguageMessages.getMessage()` warns about unused vars.

## Architecture

```
WinTestTGBot.py         main entry, glues WT <-> TG, keeps `stations` dict (station -> op call)
WinTestHandler.py       UDP listener thread + watchdog thread, WT escaping/checksum
TelegramChatManager.py  python-telegram-bot Application, all /commands, sendMessage()
BOTConfiguration.py     .env loading, logging (file/console/telegram handlers), JSON database
MuliLanguageMessages.py language packs from lang/*.json
```

Threads at runtime:
- main thread: `StopInterrupt.wait()` loop, only there to catch Ctrl+C
- `WinTestHandler.listen`: blocking select() on the UDP socket, calls back into
  `WinTestTGBot.incomingWTMessage` / `opChangeOnStation` synchronously
- `WinTestHandler.watchdog`: heartbeat timeout -> `wdFlag`
- `TelegramChatManager._start`: runs `Application.run_polling()` on its own asyncio
  loop (`self._loop`). All handlers are coroutines on that loop.

Cross-thread entry point into asyncio is `TelegramChatManager.sendMessage()`. It is
called from the WT thread, from logging handlers (any thread) and from within
handlers (loop thread). It formats, splits (4096) and hands the chunks to the loop via
`call_soon_threadsafe`. Nothing else may touch the loop from a foreign thread.

Outgoing messages: `_sendWorker` (started in `post_init`) drains per-chat FIFO queues
round robin. `_attempt()` does exactly one `send_message` and maps every exception:
RetryAfter -> per-chat not-before, NetworkError -> global backoff, Forbidden / chat not
found -> chat muted and queue dropped, ChatMigrated -> `cf.updateChatId`. Items older
than `TG_MSG_MAX_AGE` are dropped. Log records produced inside the sender carry
`extra={'no_tg': True}` so `TelegramLoggingHandler` never forwards them (this was the
feedback loop that flooded the chats). Connection loss/recovery is logged once each.

Shared mutable state without locks: `cf.chats`, `cf.users` (mutated by TG handlers,
iterated by the WT thread). Always iterate over snapshots (`list(cf.chats.items())`)
from the WT thread and use `.get()` for cross references. `WinTestTGBot.stations` is
guarded by `_stationsLock` and persisted to `STATIONS_FILE_PATH` on every change,
restored at start if younger than `WT_STATIONS_MAX_AGE`.

Users are keyed by Telegram `@username`, or `id<user id>` if they have none
(`TelegramChatManager.userKey`). All command handlers start with `_prepare()`.
Bold headers are passed as `sendMessage(chat, text, header=...)`, never as markup in
the text; everything is escaped for MarkdownV2 in `formatMessage()`.

## Win-Test protocol facts (as implemented)

- Datagram: ASCII payload + 1 checksum byte + 0x00. Checksum = (sum(bytes) | 128) % 256.
- `GAB: "FROM" "TO" "TEXT"` chat message. Empty TO = broadcast. Only broadcasts are relayed.
- `LOGIN: "STATION" "..." "CALL" "..."` / `LOGOUT: "STATION" "..."` -> op tracking.
- Escaping: `\\`, `\"`, bytes > 127 as `\ooo` octal (latin-1), `\200` = euro sign.
- Limits from `.env`: `WT_STN_LIMIT` (10), `WT_MSG_LIMIT` (79), checked before escaping.
- Own broadcasts are echoed back; `_ownMessages` filters the last 5 sent datagrams.

## Telegram facts relevant here

- Text limit 4096 chars per message (`telegram.constants.MessageLimit.MAX_TEXT_LENGTH`).
- Flood limits: ~30 msg/s bot wide, 1 msg/s per private chat, 20 msg/min per group.
  Violations raise `telegram.error.RetryAfter`.
- All outgoing text uses `parse_mode='MarkdownV2'` after `escape_markdown(version=2)`.
- PTB wraps httpx errors: `httpx.*Timeout` -> `telegram.error.TimedOut`,
  other `httpx.HTTPError` -> `telegram.error.NetworkError`. Never `except httpx.*`.
- `Application.run_polling()` installs signal handlers on non-Windows; in a background
  thread this needs `stop_signals=None`.
- Polling get_updates errors are forwarded to `add_error_handler` callbacks.

## Local development / testing

```
python3 -m venv venv && venv/bin/pip install -r requirements.txt pytest
cp .demoenv .env   # then edit
venv/bin/python WinTestTGBot.py
venv/bin/python -m pytest tests/ -q
```

`tests/` runs offline: `conftest.py` sets all `.env` keys (loopback broadcast
`127.255.255.255/255.0.0.0`, temp data dir) before the bot modules are imported,
because `BOTConfiguration` configures itself at import time. `test_telegram.py`
replaces `telegram.Bot.get_me` and `app.bot` with fakes and drives the send worker on
the real event loop; `test_integration.py` starts the whole bot with a fake
`run_polling` and feeds Win-Test datagrams via UDP. Before pushing, also run the suite
against the oldest supported library (`pip install python-telegram-bot==20.0`).

The bot needs an interface in the `BROADCAST_IP`/`WINTEST_SUBNET` subnet, otherwise
`WinTestHandler` raises `IPNotFoundException` after `WT_IP_WAIT` seconds.

Runtime artefacts live in `data/` (gitignored): `wttgbot.log` (+ rotated `.N`),
`wttgbot.json` (+ `.bak`, users and chats), `wtstations.json` (operator list).
