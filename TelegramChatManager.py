import BOTConfiguration as cf
import telegram, threading
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)
from telegram.error import TelegramError, NetworkError, RetryAfter, Forbidden, ChatMigrated, BadRequest, InvalidToken
import asyncio
import re, time
from collections import deque

TG_MAX_LEN = 4096 # telegram text message limit

def esc(text):
    ''' Escape text for MarkdownV2 '''
    return telegram.helpers.escape_markdown(text, version=2)

class TelegramChatManager:
    ''' This class provides the Chat Management used to handle all messages between Telegram and this software'''

    SEND_GAP = 0.05 # bot wide gap between two sends (telegram allows ~30 msg/s)
    CHAT_GAP_PRIVATE = 1.0 # per chat gaps, telegram allows 1 msg/s in private and 20 msg/min in group chats
    CHAT_GAP_GROUP = 3.0
    CHAT_QUEUE_MAX = 200 # pending messages per chat, the oldest are dropped
    MAX_BACKOFF = 60.0

    def __init__(self, messageToWThandler, getOPsHandler, getWinTestDump):
        ''' Construct the chat manager, with an application and the basic push capability '''
        self.username = ''
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.set_exception_handler(self.handleCoroutineException)
        threading.excepthook = cf.handleUncaughtException
        self.toWT = messageToWThandler
        self.getOPs = getOPsHandler
        self.getWTdump = getWinTestDump
        self._thread = None
        self._loopThread = None
        self._worker = None
        self.defaultLang = os.getenv('DEFAULT_LANG')
        # outgoing queue state, only touched from the event loop thread
        self._pending = {} # chat id -> deque of [timestamp, chat id, text, parse_mode]
        self._order = deque() # round robin over chats with pending messages
        self._wakeup = asyncio.Event()
        self._lastSent = {}
        self._notBefore = {}
        self._lastAny = 0.0
        self._globalNotBefore = 0.0
        self._backoff = 1.0
        self._netDown = False
        self._downSince = 0.0
        self._stale = 0

        token = os.getenv('TELEGRAM_TOKEN')
        self.bot = telegram.Bot(token=token) # only used to fetch our username, the application bot does the rest
        self._loop.run_until_complete(self._fetchUsername())
        builder = Application.builder().token(token)
        builder = builder.connect_timeout(15).read_timeout(15).write_timeout(15).pool_timeout(10)
        builder = builder.get_updates_connect_timeout(30)
        builder = builder.post_init(self._postInit).post_shutdown(self._postShutdown)
        self.app = builder.build()

        # Add the command handlers
        notEdited = ~filters.UpdateType.EDITED
        for cmd, handler in (('start', self.handleStart), ('verify', self.handleVerify), ('name', self.handleName), ('lang', self.handleLang),
                             ('mute', self.handleMute), ('confirm', self.handleConfirm), ('all', self.handleAll), ('sudo', self.handleSudo),
                             ('leave', self.handleLeave), ('dump', self.handleDump), ('makeleave', self.handleMakeLeave), ('muteall', self.handleMuteall),
                             ('plebs', self.handlePlebs), ('loglevel', self.handleLoglevel), ('help', self.handleHelp)):
            self.app.add_handler(CommandHandler(cmd, handler, filters=notEdited))
        # And the message handlers
        self._mention = re.compile(r'^@' + re.escape(self.username) + r'(?:\s+|$)', re.IGNORECASE)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE & notEdited, self.handleMessage))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS & notEdited & filters.Regex(self._mention), self.handleGroupMessage))
        self.app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, self.handleMigrate))
        self.app.add_handler(TypeHandler(Update, self._seenUpdate), group=-1) # any update proves the connection works
        self.app.add_error_handler(self.errorHandler)
        cf.log.info('[TCM] Bot sucessfully instanciated, username: ' + self.username)

    async def _fetchUsername(self):
        ''' Get our own username. Retries while the network is down (autostart before the router is up), gives up on a wrong token. '''
        delay = 5
        while True:
            try:
                self.username = (await self.bot.get_me()).username
                return
            except InvalidToken as e:
                cf.log.fatal('[TCM] Could not establish a connection to Telegram. Is the key correct? Exception: ' + str(e))
                raise SystemExit(1)
            except TelegramError as e:
                cf.log.warning('[TCM] Cannot reach Telegram (' + str(e) + '), retrying in ' + str(delay) + ' s')
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)

    async def _postInit(self, app):
        self._worker = asyncio.ensure_future(self._sendWorker())

    async def _postShutdown(self, app):
        if self._worker is not None:
            self._worker.cancel()

    def start(self):
        ''' This function will start the polling process of the Telegram bot. '''
        def _start():
            asyncio.set_event_loop(self._loop)
            self._loopThread = threading.get_ident()
            try:
                # signal handlers only work in the main thread, the bootstrap retries forever if the network is down
                self.app.run_polling(stop_signals=None, bootstrap_retries=-1)
            except Exception as e:
                cf.log.critical('[TCM] Telegram polling terminated: ' + repr(e), exc_info=e)
        # we'll do the polling in a new thread. this encapsulates it from the rest
        self._thread = threading.Thread(target=_start, daemon=True)
        self._thread.start()
        cf.log.info('[TCM] Telegram application started')
        # Send super-users the boot message
        for chat, langcode in self._superuserChats():
            self.sendMessage(chat, cf.ml.getMessage(langcode, 'BOT_BOOT'))

    def stop(self):
        ''' Send the shutdown message to the super-users and stop the polling loop, waits a few seconds at most. '''
        cf.log.debug('[TCM] Stop event')
        for chat, langcode in self._superuserChats():
            self.sendMessage(chat, cf.ml.getMessage(langcode, 'BOT_SHUTDOWN'), wait=True)
        try:
            self._loop.call_soon_threadsafe(self._loop.stop) # run_polling returns and shuts the application down
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=15)

    def _superuserChats(self):
        for user in list(cf.users):
            data = cf.users.get(user)
            if data and data['is_superuser'] == True and cf.chats.get(data['chat_id']):
                yield data['chat_id'], cf.chats[data['chat_id']]['langcode']

    # ------------------------------------------------------------------ outgoing messages

    @staticmethod
    def formatMessage(message, header=''):
        ''' Build the MarkdownV2 text: escaped message, optionally prefixed by a bold header line '''
        text = esc(message)
        if header:
            text = '*' + esc(header) + '*:\n' + text
        return text

    @staticmethod
    def splitMessage(text, limit=TG_MAX_LEN):
        ''' Split an escaped text into chunks telegram accepts, preferably at line breaks and never inside an escape sequence '''
        parts = []
        while len(text) > limit:
            cut = text.rfind('\n', limit // 2, limit)
            if cut < 0:
                cut = limit
            if (len(text[:cut]) - len(text[:cut].rstrip('\\'))) % 2 == 1: # odd number of trailing backslashes: the last one escapes text[cut]
                cut -= 1
            parts.append(text[:cut])
            text = text[cut:]
            if text.startswith('\n'):
                text = text[1:]
        if text or not parts:
            parts.append(text)
        return parts

    def sendMessage(self, chatID, message, header='', wait=False):
        '''Basic function to send a message to a specific chat, this can be called from any thread at any time. `header` is shown bold. With `wait` the message is sent once, synchronously (shutdown). '''
        if chatID == None or chatID == '':
            return
        chatID = str(chatID)
        now = time.time()
        items = [[now, chatID, text, 'MarkdownV2'] for text in self.splitMessage(self.formatMessage(message, header))]
        cf.log.debug('[TCM] Queueing message for ' + chatID + ': ' + message[:80].replace('\n', ' '))
        try:
            if wait and threading.get_ident() != self._loopThread:
                asyncio.run_coroutine_threadsafe(self._sendNow(items), self._loop).result(timeout=15)
            elif threading.get_ident() == self._loopThread:
                self._enqueue(items)
            else:
                self._loop.call_soon_threadsafe(self._enqueue, items)
        except Exception as e:
            cf.log.warning('[TCM] Could not queue a message: ' + repr(e), extra={'no_tg': True})

    def _enqueue(self, items):
        ''' Append items to their chat queue. Loop thread only. '''
        chatID = items[0][1]
        queue = self._pending.get(chatID)
        if queue is None:
            queue = self._pending[chatID] = deque()
            self._order.append(chatID)
        queue.extend(items)
        while len(queue) > self.CHAT_QUEUE_MAX:
            queue.popleft()
            self._stale += 1
        self._wakeup.set()

    async def _sendNow(self, items):
        for item in items:
            await self._attempt(item)

    def _gap(self, chatID):
        chat = cf.chats.get(chatID)
        return self.CHAT_GAP_GROUP if chat and chat['is_private'] == False else self.CHAT_GAP_PRIVATE

    def _pickChat(self, now):
        ''' Round robin: return the next chat which may send now, or (None, seconds until one may). '''
        best = None
        for _ in range(len(self._order)):
            chatID = self._order[0]
            self._order.rotate(-1)
            readyAt = max(self._lastSent.get(chatID, 0.0) + self._gap(chatID), self._notBefore.get(chatID, 0.0))
            if readyAt <= now:
                return chatID, 0.0
            best = readyAt - now if best is None else min(best, readyAt - now)
        return None, best

    async def _sendWorker(self):
        ''' The only place where messages are actually sent. Never raises, never blocks on one chat. '''
        cf.log.debug('[TCM] Send worker started')
        while True:
            try:
                maxAge = float(os.getenv('TG_MSG_MAX_AGE', '900'))
                if not self._order:
                    self._wakeup.clear()
                    await self._wakeup.wait()
                    continue
                now = time.time()
                wait = max(self._globalNotBefore, self._lastAny + self.SEND_GAP) - now
                if wait > 0:
                    await asyncio.sleep(min(wait, 1.0))
                    continue
                chatID, wait = self._pickChat(now)
                if chatID is None:
                    await asyncio.sleep(min(wait, 1.0))
                    continue
                queue = self._pending[chatID]
                item = queue[0]
                if now - item[0] > maxAge:
                    queue.popleft()
                    self._stale += 1
                    cf.log.debug('[TCM] Dropped a stale message for ' + chatID)
                elif await self._attempt(item):
                    queue.popleft()
                    self._lastSent[chatID] = self._lastAny = time.time()
                if not queue:
                    self._pending.pop(chatID, None)
                    try:
                        self._order.remove(chatID)
                    except ValueError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                cf.log.error('[TCM] Send worker error: ' + repr(e), exc_info=e, extra={'no_tg': True})
                await asyncio.sleep(1)

    async def _attempt(self, item):
        ''' One send attempt. Returns True if the item is finished (sent or dropped), False if it has to be retried later. '''
        ts, chatID, text, parse = item
        try:
            await self.app.bot.send_message(chat_id=chatID, text=text, parse_mode=parse)
            self._noteSuccess()
            return True
        except RetryAfter as e:
            retry = getattr(e, 'retry_after', 5)
            retry = retry.total_seconds() if hasattr(retry, 'total_seconds') else float(retry)
            self._notBefore[chatID] = time.time() + retry + 0.5
            cf.log.debug('[TCM] Flood control for ' + chatID + ', waiting ' + str(retry) + ' s')
        except ChatMigrated as e:
            self._migrate(chatID, str(e.new_chat_id))
        except Forbidden as e:
            self._unreachable(chatID, str(e))
            return True
        except BadRequest as e:
            reason = str(e).lower()
            if 'parse' in reason and parse is not None: # should not happen, but never lose the message over formatting
                item[3] = None
            elif 'not found' in reason or 'kicked' in reason or 'deactivated' in reason or 'blocked' in reason:
                self._unreachable(chatID, str(e))
                return True
            else:
                cf.log.warning('[TCM] The message could not be sent. Reason: ' + str(e), extra={'no_tg': True})
                return True
        except NetworkError as e: # includes TimedOut
            self._noteFailure(e)
            self._globalNotBefore = time.time() + self._backoff
            self._backoff = min(self.MAX_BACKOFF, self._backoff * 2)
        except TelegramError as e:
            cf.log.warning('[TCM] The message could not be sent. Reason: ' + repr(e), extra={'no_tg': True})
            return True
        except Exception as e:
            cf.log.error('[TCM] Unexpected error while sending: ' + repr(e), exc_info=e, extra={'no_tg': True})
            return True
        return False

    def _migrate(self, oldID, newID):
        ''' A group became a supergroup: move the database entry and the pending messages '''
        if cf.chats.get(oldID):
            cf.updateChatId(oldID, newID)
        queue = self._pending.pop(oldID, None)
        if queue is not None:
            for item in queue:
                item[1] = newID
            self._pending.setdefault(newID, deque()).extend(queue)
            if newID not in self._order:
                self._order.append(newID)
        try:
            self._order.remove(oldID)
        except ValueError:
            pass

    def _unreachable(self, chatID, reason):
        ''' The chat blocked or removed us. Mute it and drop its queue so it does not fail on every Win-Test message. '''
        cf.log.warning('[TCM] Chat ' + chatID + ' is unreachable (' + reason + '), muting it.', extra={'no_tg': True})
        if cf.chats.get(chatID):
            cf.updateChat(chatID, 'mute', 'all')
        self._pending.pop(chatID, None)
        try:
            self._order.remove(chatID)
        except ValueError:
            pass

    def _noteFailure(self, e):
        if not self._netDown:
            self._netDown, self._downSince = True, time.time()
            cf.log.warning('[TCM] Telegram is unreachable: ' + str(e), extra={'no_tg': True})

    def _noteSuccess(self):
        self._backoff = 1.0
        self._globalNotBefore = 0.0
        if self._netDown:
            self._netDown = False
            cf.log.warning('[TCM] Telegram reachable again after ' + str(int(time.time() - self._downSince)) + ' s, ' + str(self._stale) + ' stale messages dropped.')
            self._stale = 0

    async def _seenUpdate(self, update, context):
        self._noteSuccess()

    async def reply(self, update, text):
        ''' Reply to a message with already escaped MarkdownV2 text, split if needed. Never raises. '''
        message = update.effective_message
        for part in self.splitMessage(text):
            try:
                await message.reply_text(part, parse_mode='MarkdownV2')
            except BadRequest as e:
                cf.log.warning('[TCM] Reply failed (' + str(e) + '), sending plain text')
                try:
                    await message.reply_text(part)
                except TelegramError as e2:
                    cf.log.warning('[TCM] Plain reply failed too: ' + str(e2), extra={'no_tg': True})
                    return
            except NetworkError as e:
                self._noteFailure(e)
                return
            except TelegramError as e:
                cf.log.warning('[TCM] Reply failed: ' + repr(e), extra={'no_tg': True})
                return

    # ------------------------------------------------------------------ common handler logic

    @staticmethod
    def userKey(update):
        ''' Database key of the sending telegram user: the @username, or a stable id based key for users without one '''
        user = update.effective_user
        if user is None:
            return None
        return user.username if user.username else 'id' + str(user.id)

    async def _prepare(self, update, superuser=False):
        ''' Common checks of all commands. Returns (chat_id, user, langcode) or None if the command must not be executed (the reply was sent already). '''
        message = update.effective_message
        user = self.userKey(update)
        if message is None or user is None: # channel posts, anonymous admins
            return None
        chat_id = str(message.chat_id)
        private = message.chat.type == 'private'
        if private:
            if not await self.sanityCheck(update):
                return None
        else:
            if not await self.sanityCheckGroup(update):
                return None
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if superuser:
            if not private:
                await self.reply(update, esc(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP')))
                return None
            if cf.users[user]['is_superuser'] == False:
                await self.reply(update, esc(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV')))
                return None
        return chat_id, user, langcode

    # ------------------------------------------------------------------ command handlers

    async def handleStart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Start the setup conversation after the /start command'''
        message = update.effective_message
        user = self.userKey(update)
        if message is None or user is None:
            return
        chat_id = str(message.chat_id)
        chat_type = message.chat.type

        if cf.chats.get(chat_id): # chat exists in database. /start was unneccesary
            if cf.chats[chat_id]['valid'] == True:
                text = cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_VALID')
            else:
                text = cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_UNVALID')
        elif chat_type == 'private':
            langcode = update.effective_user.language_code # try to greet the user in its own language
            if not cf.ml.languageSupported(langcode):
                langcode = self.defaultLang
            if cf.users.get(user): # we already know the user. Maybe it interacted with the bot in a group?
                if cf.users[user]['chat_id'] != '': # it should not have a chat set
                    cf.log.warning('[TCM] User ' + user + ' just opend a new chat, while a old chat was existent. Overriding the stored chat.')
                cf.updateUser(user, 'chat_id', chat_id)
                cf.newChat(chat_id, langcode=langcode, is_private=True, user=user) # open a new chat, link it to the existing user
            else:
                cf.newPrivateChat(user, chat_id, langcode)
            cf.log.info('[TCM] A new private chat just started with user ' + user)
            text = cf.ml.getMessage(langcode, 'WELCOME_PRIVATE', vars={'name': update.effective_user.first_name})
        else:
            langcode = self.defaultLang
            title = message.chat.title or chat_id
            cf.newChat(chat_id, langcode=langcode, is_private=False, groupname=title, mute='none')
            cf.log.info('[TCM] A new group chat just started: ' + title)
            text = cf.ml.getMessage(langcode, 'WELCOME_GROUP')
        await self.reply(update, esc(text))

    async def handleVerify(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handly /verify command. Try to get the password. '''
        message = update.effective_message
        if message is None:
            return
        chat_id = str(message.chat_id)
        chat_type = message.chat.type

        if not cf.chats.get(chat_id):
            await self.reply(update, esc(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR')))
            return
        langcode = cf.chats[chat_id]['langcode']
        if cf.chats[chat_id]['valid'] == True:
            await self.reply(update, esc(cf.ml.getMessage(langcode, 'ALREADY_VERIFIED')))
            return
        if context.args == []: # check syntax
            await self.reply(update, esc(cf.ml.getMessage(langcode, 'INVALID_VERIFY_SYNTAX')))
            return
        key = ' '.join(context.args)
        if key == os.getenv('MAGIC_KEY'):
            if chat_type == 'private':
                text = cf.ml.getMessage(langcode, 'VERIFY_SUCCESS_PRIVATE')
            else:
                text = cf.ml.getMessage(langcode, 'VERIFY_SUCCESS_GROUP', vars={'botuname': self.username})
            cf.updateChat(chat_id, 'valid', True)
            cf.log.info('[TCM] New chat verified.')
        else:
            text = cf.ml.getMessage(langcode, 'VERIFY_FAILED')
            cf.log.warning('[TCM] Chat verification failed for chat ' + chat_id + ', wrong key with ' + str(len(key)) + ' characters.')
        await self.reply(update, esc(text))

    async def handleName(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /name commands. If no key is specified, we'll try to set the telegram username as the name. '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        charlim = int(os.getenv('WT_STN_LIMIT')) - len(os.getenv('WT_CALL_PREFIX')) - len(os.getenv('WT_CALL_SUFFIX'))
        if context.args == []: # if no name is specified, we'll try to use the TG username
            tguser = update.effective_user
            dispname = (tguser.username or tguser.first_name or '').upper()
            okMsg, failMsg = 'NAME_SET_USERNAME', 'NAME_SYNTAX_UNAME'
        else:
            dispname = ' '.join(context.args).upper()
            okMsg, failMsg = 'NAME_SET_SUCCESS', 'NAME_SET_FAILED'
        try:
            dispname.encode('cp1252')
            encodable = '\x00' not in dispname
        except UnicodeEncodeError:
            encodable = False
        if not encodable:
            text = cf.ml.getMessage(langcode, 'NAME_ENCODING_FAILED')
        elif 0 < len(dispname) <= charlim:
            cf.updateUser(user, 'wt_dispname', dispname)
            text = cf.ml.getMessage(langcode, okMsg, vars={'uname': dispname, 'dispname': dispname})
            cf.log.info('[TCM] User ' + user + ' updated its Win-Test display name to ' + dispname)
        else:
            text = cf.ml.getMessage(langcode, failMsg, vars={'uname': dispname, 'charlim': charlim})
        await self.reply(update, esc(text))

    async def handleLang(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /lang commands. This switches the language of the current chat. '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        if context.args == []:
            text = cf.ml.getMessage(langcode, 'LANG_SYNTAX', vars={'languages': cf.ml.getLanguagesString()})
        else:
            newLangcode = ' '.join(context.args).lower()
            if cf.ml.languageSupported(newLangcode):
                cf.updateChat(chat_id, 'langcode', newLangcode)
                cf.log.info('[TCM] User ' + user + ' just updated the lanuage for a chat to ' + newLangcode)
                text = cf.ml.getMessage(newLangcode, 'LANG_SUCCESS')
            else:
                text = cf.ml.getMessage(langcode, 'LANG_NOT_FOUND', vars={'languages': cf.ml.getLanguagesString()})
        await self.reply(update, esc(text))

    async def handleMute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /mute commands. This mutes Win-Test Messages into this chat. '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        private = cf.chats[chat_id]['is_private']
        syntax = 'MUTE_SYNTAX_PRV' if private else 'MUTE_SYNTAX_GRP'
        mute = ' '.join(context.args).lower()
        if mute == 'all':
            text = cf.ml.getMessage(langcode, 'MUTE_ALL')
            cf.updateChat(chat_id, 'mute', 'all')
            cf.log.info('[TCM] User ' + user + ' muted a chat.')
        elif mute == 'own':
            if private:
                text = cf.ml.getMessage(langcode, 'MUTE_OWN_PRV')
                cf.updateChat(chat_id, 'mute', 'own')
                cf.log.info('[TCM] User ' + user + ' muted his own messages.')
            else:
                text = cf.ml.getMessage(langcode, 'MUTE_OWN_GRP')
        elif mute == 'none':
            text = cf.ml.getMessage(langcode, 'MUTE_NONE')
            cf.updateChat(chat_id, 'mute', 'none')
            cf.log.info('[TCM] User ' + user + ' unmuted a chat.')
        else:
            text = cf.ml.getMessage(langcode, syntax)
        await self.reply(update, esc(text))

    async def _handleSwitch(self, update, context, key, syntaxMsg, onMsg, offMsg, logName):
        ''' Shared logic of the /confirm and /all on|off switches '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        newState = ' '.join(context.args).lower()
        if newState == 'on':
            text = cf.ml.getMessage(langcode, onMsg)
            cf.updateChat(chat_id, key, True)
            cf.log.info('[TCM] User ' + user + ' enabled ' + logName)
        elif newState == 'off':
            text = cf.ml.getMessage(langcode, offMsg)
            cf.updateChat(chat_id, key, False)
            cf.log.info('[TCM] User ' + user + ' disabled ' + logName)
        else:
            text = cf.ml.getMessage(langcode, syntaxMsg)
        await self.reply(update, esc(text))

    async def handleConfirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /confirm commands. This enables/disables the confirmation messages weather the Message arrived to Win-Test. '''
        await self._handleSwitch(update, context, 'wt_confirm', 'CONFIRM_SYNTAX', 'CONFIRM_ON', 'CONFIRM_OFF', 'Win-Test confirmation messages.')

    async def handleAll(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /all command. This enables/disables the Telegram to Telegram notifications. (Cross chat notifications) '''
        await self._handleSwitch(update, context, 'tg_to_tg', 'ALL_SYNTAX', 'ALL_ON', 'ALL_OFF', 'TG to TG messages.')

    async def handleSudo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /sudo commands. This makes the current user a Super-User. '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        if cf.chats[chat_id]['is_private'] == False:
            text = cf.ml.getMessage(langcode, 'SUDO_GROUP')
        elif cf.users[user]['is_superuser'] == True:
            text = cf.ml.getMessage(langcode, 'SUDO_ALREADY')
        elif context.args == []:
            text = cf.ml.getMessage(langcode, 'SUDO_SYNTAX')
        elif ' '.join(context.args) == os.getenv('SUPER_USER_KEY'):
            text = cf.ml.getMessage(langcode, 'SUDO_SUCCESS')
            cf.updateUser(user, 'is_superuser', True)
            cf.log.info('[TCM] User ' + user + ' is now a superuser.')
        else:
            text = cf.ml.getMessage(langcode, 'SUDO_FAILED')
            cf.log.warning('[TCM] Superuser verification failed by user ' + user + ', wrong key with ' + str(len(' '.join(context.args))) + ' characters.')
        await self.reply(update, esc(text))

    async def handleLeave(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /leave commands. This deletes all stored data, without asking!'''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        private = cf.chats[chat_id]['is_private']
        cf.remove(chat_id)
        if private:
            cf.log.info('[TCM] User ' + user + ' deletet itself.')
        else:
            cf.log.info('[TCM] User ' + user + ' just removed the group ' + str(update.effective_message.chat.title))
        await self.reply(update, esc(cf.ml.getMessage(langcode, 'LEAVE_SUCCESS')))

    async def handleDump(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /dump commands. This displays all stored data to super users. '''
        prep = await self._prepare(update, superuser=True)
        if prep is None:
            return
        chat_id, user, langcode = prep
        dump_msg = esc(cf.ml.getMessage(langcode, 'DUMP_PREFIX')) + '\n\n'
        for user in list(cf.users):
            udata = cf.users.get(user)
            if udata is None:
                continue
            if udata['chat_id'] != '' and cf.chats.get(udata['chat_id']):
                data_dump = dict(udata, **cf.chats[udata['chat_id']])
                for key in ('groupname', 'chat_id', 'is_private'): # remove the not printed keys, otherwise a warning would arise
                    data_dump.pop(key, None)
                data_dump['user'] = user
                dump_msg += esc(cf.ml.getMessage(langcode, 'DUMP_USER_PRV', vars=data_dump)) + '\n'
            else:
                data_dump = dict(udata)
                data_dump.pop('chat_id', None)
                data_dump['user'] = user
                dump_msg += esc(cf.ml.getMessage(langcode, 'DUMP_USER', vars=data_dump)) + '\n'
        anyGroup = False
        for chat in list(cf.chats):
            cdata = cf.chats.get(chat)
            if cdata and cdata['is_private'] == False:
                if anyGroup == False:
                    dump_msg += '\n' + esc(cf.ml.getMessage(langcode, 'DUMP_MIDFIX')) + '\n\n'
                    anyGroup = True
                data_dump = dict(cdata)
                data_dump.pop('is_private')
                data_dump.pop('user')
                dump_msg += esc(cf.ml.getMessage(langcode, 'DUMP_GRPchat', vars=data_dump)) + '\n'
        dump_msg += '\n' + esc(cf.ml.getMessage(langcode, 'DUMP_SUFFIX', vars=self.getWTdump()))
        await self.reply(update, dump_msg)

    async def handleMakeLeave(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /makeleave commands. This allows super users to remove users. '''
        prep = await self._prepare(update, superuser=True)
        if prep is None:
            return
        chat_id, user, langcode = prep
        if context.args == []: # check syntax
            await self.reply(update, esc(cf.ml.getMessage(langcode, 'MAKELEAVE_SYNTAX')))
            return
        name = ' '.join(context.args)
        if cf.users.get(name) != None:
            text = cf.ml.getMessage(langcode, 'MAKELEAVE_USER_SUCCESS', vars={'user': name})
            cf.removeUser(name)
            cf.log.info('[TCM] Super-user ' + user + ' just removed ' + name)
        else:
            text = cf.ml.getMessage(langcode, 'MAKELEAVE_NOT_FOUND')
            for chat in list(cf.chats):
                if cf.chats[chat]['groupname'] == name:
                    text = cf.ml.getMessage(langcode, 'MAKELEAVE_GRP_SUCCESS', vars={'groupname': name})
                    cf.remove(chat)
                    cf.log.info('[TCM] Super-user ' + user + ' just removed ' + name)
                    break
        await self.reply(update, esc(text))

    async def handleMuteall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /muteall commands. This allows super users to mute all chats after a contest. '''
        prep = await self._prepare(update, superuser=True)
        if prep is None:
            return
        chat_id, user, langcode = prep
        for chat in list(cf.chats):
            if chat == chat_id or cf.chats.get(chat) is None:
                continue
            if cf.chats[chat]['mute'] != 'all':
                cf.updateChat(chat, 'mute', 'all')
                us_langcode = cf.chats[chat]['langcode']
                self.sendMessage(chat, cf.ml.getMessage(us_langcode, 'MUTE_ALL_PRV' if cf.chats[chat]['is_private'] == True else 'MUTE_ALL_GRP'))
        cf.log.info('[TCM] Super-User ' + user + ' just muted all chats.')
        await self.reply(update, esc(cf.ml.getMessage(langcode, 'MUTE_ALL_SUCCESS')))

    async def handlePlebs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /plebs commands. This removes the super-user status from a user. '''
        prep = await self._prepare(update, superuser=True)
        if prep is None:
            return
        chat_id, user, langcode = prep
        cf.updateUser(user, 'is_superuser', False)
        cf.updateUserLogging(user, 'none')
        cf.log.info('[TCM] Super-User ' + user + ' gave up on its super-user rights')
        await self.reply(update, esc(cf.ml.getMessage(langcode, 'TO_PLEBS')))

    async def handleLoglevel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /loglevel commands. This allows super-users to set a loglevel '''
        prep = await self._prepare(update, superuser=True)
        if prep is None:
            return
        chat_id, user, langcode = prep
        if context.args != [] and cf.updateUserLogging(user, ' '.join(context.args)) == 0:
            text = cf.ml.getMessage(langcode, 'LOGLEVEL_SUCCESS')
        else:
            text = cf.ml.getMessage(langcode, 'LOGLEVEL_SYNTAX')
        await self.reply(update, esc(text))

    async def handleHelp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /help commands. This displays all commands and the current settings. '''
        prep = await self._prepare(update)
        if prep is None:
            return
        chat_id, user, langcode = prep
        settings = {'wt_dispname': cf.users[user]['wt_dispname'],
                    'languages': cf.ml.getLanguagesString(),
                    'mute': cf.chats[chat_id]['mute'],
                    'wt_confirm': 'on' if cf.chats[chat_id]['wt_confirm'] == True else 'off',
                    'tg_to_tg': 'on' if cf.chats[chat_id]['tg_to_tg'] == True else 'off'}
        if cf.chats[chat_id]['is_private'] == False:
            settings['botuname'] = self.username
            text = cf.ml.getMessage(langcode, 'HELP_GRP', vars=settings)
        elif cf.users[user]['is_superuser'] == True:
            settings['log_level'] = cf.users[user]['log_level']
            text = cf.ml.getMessage(langcode, 'HELP_SUSER', vars=settings)
        else:
            text = cf.ml.getMessage(langcode, 'HELP_PRV', vars=settings)
        await self.reply(update, esc(text) + '\n\n')

    async def handleMigrate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' A group chat was converted to a supergroup, telegram assigns a new chat id '''
        message = update.effective_message
        if message is not None and message.migrate_to_chat_id:
            self._migrate(str(message.chat_id), str(message.migrate_to_chat_id))

    # ------------------------------------------------------------------ chat messages

    async def handleMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Handle the incoming messages and send them to WT'''
        if update.effective_message is None or update.effective_user is None:
            return
        if await self.sanityCheck(update):
            await self._relay(update, update.effective_message.text)

    async def handleGroupMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Handle the incoming group messages and send them to WT'''
        if update.effective_message is None or update.effective_user is None:
            return
        text = self._mention.sub('', update.effective_message.text, count=1)
        cf.log.debug('[TCM] Group message: ' + text + ' from chat_id : ' + str(update.effective_message.chat_id) + ' user: ' + str(self.userKey(update)))
        if text != '' and await self.sanityCheckGroup(update):
            await self._relay(update, text)

    async def _relay(self, update, text):
        ''' Forward a telegram message to Win-Test and to the other telegram chats '''
        chat_id = str(update.effective_message.chat_id)
        user = self.userKey(update)
        confirm = cf.chats[chat_id]['wt_confirm']
        langcode = cf.chats[chat_id]['langcode']
        udata = cf.users.get(user)
        if udata and udata['wt_dispname'] != '':
            dispname = os.getenv('WT_CALL_PREFIX') + udata['wt_dispname'] + os.getenv('WT_CALL_SUFFIX')
            msg = ''
        else:
            dispname = cf.ml.getMessage(self.defaultLang, 'BOT_STATION')
            msg = cf.ml.getMessage(langcode, 'REQUEST_WTNAME', vars={'name': update.effective_user.first_name})
        resp = self._forwardToWT(dispname, text, langcode)

        if resp == '':
            if confirm:
                resp = cf.ml.getMessage(langcode, 'WT_CONFIRM')
            ops = self.getOPs()
            for chat in list(cf.chats):
                cdata = cf.chats.get(chat)
                if chat == chat_id or cdata is None or cdata['valid'] == False:
                    continue
                if cdata['tg_to_tg'] == True and cdata['mute'] != 'all':
                    owner = cf.users.get(cdata['user'])
                    if cdata['is_private'] == True and cdata['mute'] == 'own' and owner and owner['wt_dispname'].upper() in ops:
                        continue
                    self.sendMessage(chat, text, header=dispname)

        if msg != '' and resp != '':
            msg += '\n\n ---- \n\n' + resp
        else:
            msg += resp
        if msg != '':
            await self.reply(update, esc(msg))

    # ------------------------------------------------------------------ errors and checks

    async def errorHandler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' If a uncaught telegram error within a telegram message arises. Network errors of the polling loop are retried by the library, so they are only noted. '''
        error = context.error
        if isinstance(error, NetworkError):
            self._noteFailure(error)
            return
        cf.log.error('[TCM] An uncaught exception in the telegram module occurred. This bot will continue to run. \nException: ' + str(error)[:500], exc_info=error)

    def handleCoroutineException(self, loop, context):
        error = context.get('exception')
        if isinstance(error, NetworkError):
            self._noteFailure(error)
            return
        cf.log.error('[TCM] A coroutine failed to execute! \nException: ' + str(error if error else context.get('message'))[:500], exc_info=error)

    async def sanityCheck(self, update, silent = False):
        ''' Sanity check to limit access only to existing well-behaved users. This check is for private chats.'''
        chat_id = str(update.effective_message.chat_id)
        user = self.userKey(update)

        if not cf.chats.get(chat_id):
            if not silent:
                await self.reply(update, esc(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR')))
                cf.log.warning('[TCM] Sanity check failed. Unknown chat.')
            return False
        langcode = cf.chats[chat_id]['langcode']

        if cf.chats[chat_id]['valid'] == False:
            if not silent:
                await self.reply(update, esc(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR')))
                cf.log.warning('[TCM] Sanity check failed. User not verified.')
            return False

        if user != cf.chats[chat_id]['user']:
            oldUser = cf.chats[chat_id]['user']
            if cf.users.get(oldUser) != None and cf.users.get(user) == None:
                cf.updateUsername(oldUser, user)
                cf.log.info('[TCM] Changing username from user ' + oldUser + ' to ' + user)
            elif cf.users.get(user) == None:
                cf.newUser(user, chat=chat_id)

        if cf.chats[chat_id]['user'] != user:
            cf.log.warning('[TCM] Database inconsistency. Chat points to wrong user. Fixing that.')
            cf.updateChat(chat_id, 'user', user)
        if cf.users[user]['chat_id'] != chat_id:
            cf.log.warning('[TCM] Database inconsistency. User points to wrong chat. Fixing that.')
            cf.updateUser(user, 'chat_id', chat_id)

        return True

    async def sanityCheckGroup(self, update, silent = False):
        ''' Sanity check to limit access only to existing well-behaved users. '''
        chat_id = str(update.effective_message.chat_id)
        if not cf.chats.get(chat_id):
            if not silent:
                await self.reply(update, esc(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR')))
                cf.log.warning('[TCM] Sanity check failed. Unknown chat.')
            return False
        langcode = cf.chats[chat_id]['langcode']
        if cf.chats[chat_id]['valid'] == False:
            if not silent:
                await self.reply(update, esc(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR')))
                cf.log.warning('[TCM] Sanity check failed. User not verified.')
            return False
        return True

    def _forwardToWT(self, dispname, message, langcode):
        status = self.toWT(dispname, message)
        if status == 0:
            return ''
        elif status == 1:
            return cf.ml.getMessage(langcode, 'WT_ENCODING_ERROR')
        elif status == 2:
            return cf.ml.getMessage(langcode, 'WT_MSG_LONG_ERROR', vars={'charlimit': os.getenv('WT_MSG_LIMIT')})
        elif status == 3:
            charlimit = int(os.getenv('WT_STN_LIMIT')) - len(os.getenv('WT_CALL_PREFIX')) - len(os.getenv('WT_CALL_SUFFIX'))
            return cf.ml.getMessage(langcode, 'WT_STN_LONG_ERROR', vars={'stnname': dispname, 'charlimit': str(charlimit)})
        else:
            cf.log.error('[TCM] Unknown response code from BOT!')
            return cf.ml.getMessage(langcode, 'UNKNOWN_ERROR')
