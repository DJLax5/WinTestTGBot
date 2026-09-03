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
handlers (loop thread). Anything touching the loop from a foreign thread must use
`asyncio.run_coroutine_threadsafe` / `loop.call_soon_threadsafe`.

Shared mutable state without locks: `cf.chats`, `cf.users` (mutated by TG handlers,
iterated by the WT thread), `WinTestTGBot.stations` (written by WT thread, read by
TG thread). Always iterate over snapshots (`list(cf.chats)`) from the WT thread.

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
```

The bot needs an interface in the `BROADCAST_IP`/`WINTEST_SUBNET` subnet, otherwise
`WinTestHandler` raises `IPNotFoundException` at startup. For tests use
`BROADCAST_IP=127.255.255.255`, `WINTEST_SUBNET=255.0.0.0` and feed datagrams built
with `WinTestHandler.toUDPmsg()` into `127.0.0.1:BROADCAST_PORT`.

`BOTConfiguration` runs its setup at import time (reads `.env`, creates log and data
files). Tests must set the environment variables before importing any bot module.

Runtime artefacts live in `data/` (gitignored): `wttgbot.log` (+ rotated `.N`),
`wttgbot.json` (users and chats).
