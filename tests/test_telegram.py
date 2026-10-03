import asyncio, threading, time, logging, os
from types import SimpleNamespace
import pytest
import telegram
from telegram.error import TimedOut, NetworkError, RetryAfter, Forbidden, BadRequest
import BOTConfiguration as cf
import TelegramChatManager as tcmmod
from TelegramChatManager import TelegramChatManager


class FakeBot:
    ''' Records sent messages, raises scripted exceptions first '''
    def __init__(self):
        self.sent = []
        self.errors = {} # chat id -> list of exceptions to raise before succeeding
        self.calls = 0

    async def send_message(self, chat_id, text, parse_mode=None):
        self.calls += 1
        errs = self.errors.get(str(chat_id))
        if errs:
            raise errs.pop(0)
        self.sent.append((str(chat_id), text, parse_mode))


class FakeMessage:
    def __init__(self, chat_id, chat_type='private', text='', title=None):
        self.chat_id = chat_id
        self.chat = SimpleNamespace(type=chat_type, title=title)
        self.text = text
        self.migrate_to_chat_id = None
        self.replies = []

    async def reply_text(self, text, parse_mode=None):
        self.replies.append((text, parse_mode))


def fake_update(chat_id, user_id=1, username=None, first_name='Fab', chat_type='private', text='', title=None):
    msg = FakeMessage(chat_id, chat_type, text, title)
    user = SimpleNamespace(id=user_id, username=username, first_name=first_name, language_code='en')
    return SimpleNamespace(effective_message=msg, effective_user=user, message=msg)


def ctx(*args):
    return SimpleNamespace(args=list(args))


class WTStub:
    def __init__(self):
        self.sent, self.status = [], 0

    def publish(self, origin, message):
        self.sent.append((origin, message))
        return self.status


@pytest.fixture
def tcm(monkeypatch, fresh_db):
    async def get_me(self):
        return SimpleNamespace(username='WinTestBot')
    monkeypatch.setattr(telegram.Bot, 'get_me', get_me)
    monkeypatch.setattr(TelegramChatManager, 'CHAT_GAP_PRIVATE', 0.05)
    monkeypatch.setattr(TelegramChatManager, 'CHAT_GAP_GROUP', 0.2)
    monkeypatch.setattr(TelegramChatManager, 'SEND_GAP', 0.0)
    wt = WTStub()
    t = TelegramChatManager(wt.publish, lambda: ['DL1OP'], lambda: {'wt_heartbeat': True, 'stations': 'RUN1, OP: DL1OP\n'})
    t.fake = FakeBot()
    t.app.bot = t.fake
    t.wt = wt
    yield t
    if t._loop.is_running():
        t._loop.call_soon_threadsafe(t._loop.stop)
        t._thread.join(5)
    t._loop.close()


@pytest.fixture
def running(tcm):
    ''' run the event loop with the send worker in a background thread, like run_polling would '''
    def run():
        asyncio.set_event_loop(tcm._loop)
        tcm._loopThread = threading.get_ident()
        tcm._worker = tcm._loop.create_task(tcm._sendWorker())
        tcm._loop.run_forever()
    tcm._thread = threading.Thread(target=run, daemon=True)
    tcm._thread.start()
    time.sleep(0.05)
    return tcm


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def run_async(tcm, coro):
    return tcm._loop.run_until_complete(coro)


# ---------------------------------------------------------------- formatting

def test_format_header_is_bold_and_escaped():
    text = TelegramChatManager.formatMessage('hello_world 1.5', header='RUN1 / DL1OP')
    assert text == '*RUN1 / DL1OP*:\nhello\\_world 1\\.5'
    assert TelegramChatManager.formatMessage('a<b>b') == 'a<b\\>b' # no markup from user text


def test_split_message():
    lines = ['line ' + str(i) + ' ' + 'x' * 40 for i in range(200)]
    text = '\n'.join(lines)
    parts = TelegramChatManager.splitMessage(text)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)
    assert '\n'.join(parts) == text # split at line breaks only, nothing lost
    single = 'y' * 5000
    parts = TelegramChatManager.splitMessage(single)
    assert ''.join(parts) == single and len(parts[0]) == 4096
    escaped = 'z' * 4095 + '\\.' + 'z' * 10 # escape sequence at the cut position
    parts = TelegramChatManager.splitMessage(escaped)
    assert parts[0] == 'z' * 4095 and parts[1].startswith('\\.')
    assert TelegramChatManager.splitMessage('') == ['']


def test_mention_regex(tcm):
    assert tcm._mention.match('@WinTestBot hello')
    assert tcm._mention.match('@wintestbot hello')
    assert tcm._mention.match('@WinTestBot')
    assert not tcm._mention.match('@WinTestBotX hello')
    assert tcm._mention.sub('', '@wintestbot  hi there', count=1) == 'hi there'


# ---------------------------------------------------------------- queue and network

def test_queue_from_foreign_thread(running):
    running.sendMessage('1', 'hello', header='RUN1')
    assert wait_for(lambda: len(running.fake.sent) == 1)
    assert running.fake.sent[0] == ('1', '*RUN1*:\nhello', 'MarkdownV2')


def test_long_message_is_split_in_order(running):
    running.sendMessage('1', '\n'.join('row %d %s' % (i, 'x' * 50) for i in range(200)))
    assert wait_for(lambda: len(running.fake.sent) >= 3)
    time.sleep(0.2)
    joined = '\n'.join(s[1] for s in running.fake.sent)
    assert joined.startswith('row 0') and joined.rstrip().endswith('x' * 50)


def test_network_outage_recovers_without_log_loop(running, caplog):
    caplog.set_level(logging.DEBUG, logger='BOTConfiguration')
    running.fake.errors['1'] = [TimedOut(), NetworkError('httpx.ConnectError: boom'), TimedOut()]
    running._backoff = 0.05
    running.sendMessage('1', 'after outage')
    assert wait_for(lambda: len(running.fake.sent) == 1)
    assert running._netDown == False and running._backoff == 1.0
    net = [r for r in caplog.records if 'unreachable' in r.getMessage() or 'reachable again' in r.getMessage()]
    assert len(net) == 2
    assert getattr(net[0], 'no_tg', False) == True # the outage itself is never pushed to telegram
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_retry_after_does_not_block_other_chats(running, fresh_db):
    cf.newChat('-5', is_private=False, groupname='grp')
    running.fake.errors['-5'] = [RetryAfter(1)]
    running.sendMessage('-5', 'group msg')
    running.sendMessage('7', 'private msg')
    assert wait_for(lambda: len(running.fake.sent) >= 1)
    assert running.fake.sent[0][0] == '7'
    assert wait_for(lambda: len(running.fake.sent) == 2, timeout=4)
    assert running.fake.sent[1][0] == '-5'


def test_forbidden_mutes_chat_and_drops_queue(running, fresh_db):
    cf.newPrivateChat('alice', '9')
    cf.updateChat('9', 'mute', 'none')
    running.fake.errors['9'] = [Forbidden('bot was blocked by the user')]
    # queue both in one loop callback, otherwise 'two' can arrive after the drop and is legitimately sent
    running._loop.call_soon_threadsafe(lambda: (running.sendMessage('9', 'one'), running.sendMessage('9', 'two')))
    assert wait_for(lambda: cf.chats['9']['mute'] == 'all')
    time.sleep(0.2)
    assert running.fake.sent == [] and running.fake.calls == 1 and '9' not in running._pending


def test_bad_request_chat_not_found(running, fresh_db):
    cf.newChat('-8', is_private=False, groupname='gone')
    running.fake.errors['-8'] = [BadRequest('Chat not found')]
    running.sendMessage('-8', 'x')
    assert wait_for(lambda: cf.chats['-8']['mute'] == 'all')


def test_parse_error_falls_back_to_plain(running):
    running.fake.errors['1'] = [BadRequest("Can't parse entities")]
    running.sendMessage('1', 'text')
    assert wait_for(lambda: len(running.fake.sent) == 1)
    assert running.fake.sent[0][2] is None


def test_stale_messages_are_dropped(running, monkeypatch):
    monkeypatch.setenv('TG_MSG_MAX_AGE', '0.2')
    running.fake.errors['1'] = [TimedOut()] * 50
    running._backoff = 0.05
    running.sendMessage('1', 'old news')
    time.sleep(0.6)
    assert running.fake.sent == [] and running._stale == 1 and '1' not in running._pending


def test_queue_overflow_drops_oldest(running):
    running._loop.call_soon_threadsafe(lambda: [running._enqueue([[time.time(), '3', str(i), 'MarkdownV2']]) for i in range(250)])
    time.sleep(0.1)
    assert wait_for(lambda: '3' not in running._pending, timeout=30)
    assert running.fake.sent[0][1] == '50' and len(running.fake.sent) == 200


def test_send_wait_and_no_username_callback_signature(running, fresh_db):
    running.sendMessage('1', 'sync', wait=True)
    assert running.fake.sent[-1][1] == 'sync'
    cf.messageLogCallback = running.sendMessage
    cf.messageLogCallback('1', 'log line') # two positional args as used by the logging handler
    assert wait_for(lambda: len(running.fake.sent) == 2)


# ---------------------------------------------------------------- handlers

def test_start_and_message_without_username(tcm, fresh_db):
    up = fake_update(100, user_id=100, username=None)
    run_async(tcm, tcm.handleStart(up, ctx()))
    assert cf.chats['100']['user'] == 'id100' and cf.users['id100']['chat_id'] == '100'
    assert cf.chats['100']['langcode'] == 'en'
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    assert cf.chats['100']['valid'] == True
    up = fake_update(100, user_id=100, username=None, text='hello wt')
    run_async(tcm, tcm.handleMessage(up, ctx()))
    assert tcm.wt.sent == [('TG BOT', 'hello wt')] # no display name yet
    assert 'display name' in up.effective_message.replies[0][0]
    run_async(tcm, tcm.handleName(up, ctx()))
    assert cf.users['id100']['wt_dispname'] == 'FAB' # falls back to the first name
    up = fake_update(100, user_id=100, username=None, text='second')
    run_async(tcm, tcm.handleMessage(up, ctx()))
    assert tcm.wt.sent[-1] == ('FAB/TG', 'second')


def test_username_change_and_display_name_encoding(tcm, fresh_db):
    up = fake_update(5, user_id=5, username='alice')
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    up = fake_update(5, user_id=5, username='alice2')
    run_async(tcm, tcm.handleName(up, ctx('DL1', 'ABC')))
    assert 'alice' not in cf.users and cf.users['alice2']['wt_dispname'] == 'DL1 ABC'
    run_async(tcm, tcm.handleName(up, ctx('\U0001F600')))
    assert cf.users['alice2']['wt_dispname'] == 'DL1 ABC'
    assert 'latin' in up.effective_message.replies[-1][0]


def test_wrong_keys_are_not_logged(tcm, fresh_db, caplog):
    up = fake_update(6, user_id=6, username='bob')
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleVerify(up, ctx('sekret-typo')))
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    run_async(tcm, tcm.handleSudo(up, ctx('super-sekret')))
    assert 'sekret' not in caplog.text
    assert cf.users['bob']['is_superuser'] == False
    run_async(tcm, tcm.handleSudo(up, ctx('super-secret')))
    assert cf.users['bob']['is_superuser'] == True


def test_group_flow_and_supergroup_migration(tcm, fresh_db):
    up = fake_update(-1, user_id=7, username='carol', chat_type='group', title='Contest')
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    assert cf.chats['-1']['valid'] and cf.chats['-1']['user'] == ''
    run_async(tcm, tcm.handleVerify(up, ctx('secret'))) # already verified must not corrupt the group entry
    assert cf.chats['-1']['user'] == '' and 'carol' not in cf.users
    up = fake_update(-1, user_id=7, username='carol', chat_type='group', text='@wintestbot hi ops')
    run_async(tcm, tcm.handleGroupMessage(up, ctx()))
    assert tcm.wt.sent == [('TG BOT', 'hi ops')]
    mig = fake_update(-1, user_id=7, username='carol', chat_type='supergroup')
    mig.effective_message.migrate_to_chat_id = -1001
    run_async(tcm, tcm.handleMigrate(mig, ctx()))
    assert '-1' not in cf.chats and cf.chats['-1001']['groupname'] == 'Contest'


def test_dump_is_split_and_superuser_only(tcm, fresh_db):
    for i in range(80):
        cf.newPrivateChat('user%02d' % i, str(1000 + i), wt_dispname='DL%dXX' % i)
        cf.updateChat(str(1000 + i), 'valid', True)
    up = fake_update(1000, user_id=1000, username='user00')
    run_async(tcm, tcm.handleDump(up, ctx()))
    assert len(up.effective_message.replies) == 1 and 'super' in up.effective_message.replies[0][0]
    cf.updateUser('user00', 'is_superuser', True)
    up = fake_update(1000, user_id=1000, username='user00')
    run_async(tcm, tcm.handleDump(up, ctx()))
    replies = up.effective_message.replies
    assert len(replies) > 1 and all(len(r[0]) <= 4096 for r in replies)
    assert 'DL79XX' in ''.join(r[0] for r in replies)


def test_anonymous_sender_is_ignored(tcm, fresh_db):
    up = fake_update(-2, chat_type='group')
    up.effective_user = None
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleHelp(up, ctx()))
    assert cf.chats == {} and up.effective_message.replies == []


def test_station_too_long_error_path(tcm, fresh_db):
    tcm.wt.status = 3
    assert 'too long' in tcm._forwardToWT('X' * 20, 'msg', 'en')
