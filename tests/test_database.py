import os, json, logging
import BOTConfiguration as cf


def test_store_is_pretty_atomic_and_backed_up(fresh_db):
    path = os.getenv('DATABASE_FILE_PATH')
    cf.newPrivateChat('alice', '1', wt_dispname='DL1ABC')
    text = open(path, encoding='utf-8').read()
    assert text.count('\n') > 5 # human readable, not one line
    assert json.loads(text)['users']['alice']['wt_dispname'] == 'DL1ABC'
    cf.newUser('bob')
    assert os.path.exists(path + '.bak')
    assert 'bob' not in json.load(open(path + '.bak'))['users']
    assert not os.path.exists(path + '.tmp')


def test_load_falls_back_to_backup(fresh_db):
    path = os.getenv('DATABASE_FILE_PATH')
    cf.newPrivateChat('alice', '1')
    cf.newUser('bob')
    with open(path, 'w') as f:
        f.write('{"users": {"tru') # simulated crash while writing
    chats, users = cf.loadDatabase()
    assert 'alice' in users and 'bob' not in users


def test_load_missing_file(fresh_db):
    path = os.getenv('DATABASE_FILE_PATH')
    for p in (path, path + '.bak'):
        if os.path.exists(p):
            os.remove(p)
    assert cf.loadDatabase() == ({}, {})


def test_check_database_repairs():
    chats = {'1': {'is_private': True, 'user': 'ghost'}, '2': {'langcode': 'de'}, '3': {'is_private': False}}
    users = {'alice': {'chat_id': '99'}, 'broken': 'x'}
    chats, users, modified = cf.checkDatabase(chats, users)
    assert modified
    assert '2' not in chats and 'broken' not in users
    assert chats['1']['user'] == '' and chats['1']['mute'] == 'own' and chats['1']['langcode'] == 'en'
    assert chats['3']['mute'] == 'none' and chats['3']['groupname'] == ''
    assert users['alice'] == {'chat_id': '', 'wt_dispname': '', 'log_level': 'none', 'is_superuser': False}
    assert cf.checkDatabase(chats, users)[2] == False


def test_check_database_many_entries_no_recursion():
    chats = {str(i): {'is_private': True} for i in range(3000)}
    chats, users, modified = cf.checkDatabase(chats, {})
    assert modified and len(chats) == 3000


def test_update_chat_id(fresh_db):
    cf.newPrivateChat('alice', '1')
    cf.newChat('-100', is_private=False, groupname='grp')
    cf.updateChatId('-100', '-1001')
    assert '-100' not in cf.chats and cf.chats['-1001']['groupname'] == 'grp'
    cf.updateChatId('1', '5')
    assert cf.users['alice']['chat_id'] == '5' and cf.chats['5']['user'] == 'alice'


def test_remove_private_chat_with_missing_user(fresh_db):
    cf.newPrivateChat('alice', '1')
    cf.users.pop('alice')
    cf.remove('1')
    assert '1' not in cf.chats


class TestTelegramLoggingHandler:
    def setup_method(self):
        self.sent = []
        self.old = cf.messageLogCallback
        cf.messageLogCallback = lambda chat, msg: self.sent.append(msg)
        self.handler = cf.TelegramLoggingHandler('42', logging.WARNING)

    def teardown_method(self):
        cf.messageLogCallback = self.old

    def record(self, msg, level=logging.ERROR, **extra):
        rec = logging.LogRecord('BOTConfiguration', level, __file__, 1, msg, None, None)
        for k, v in extra.items():
            setattr(rec, k, v)
        return rec

    def test_level_and_format(self):
        self.handler.emit(self.record('info msg', logging.INFO))
        assert self.sent == []
        self.handler.emit(self.record('err %s')) # never formatted by another handler before
        assert self.sent[-1].endswith('[ERROR] err %s')

    def test_no_tg_records_skipped(self):
        self.handler.emit(self.record('from sender', no_tg=True))
        assert self.sent == []

    def test_rate_limit_and_summary(self):
        for i in range(25):
            self.handler.emit(self.record('e' + str(i)))
        assert len(self.sent) == cf.TelegramLoggingHandler.RATE_LIMIT
        self.handler._windowStart -= cf.TelegramLoggingHandler.RATE_WINDOW + 1
        self.handler.emit(self.record('after window'))
        assert '15 further log messages' in self.sent[-2]
        assert self.sent[-1].endswith('after window')
