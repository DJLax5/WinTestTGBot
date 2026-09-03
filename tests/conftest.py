''' Test setup. BOTConfiguration configures itself at import time from the environment, so all keys are set here before any bot module is imported. '''
import os, sys, tempfile
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix='wttgbot_test_')

os.environ.update({
    'BROADCAST_IP': '127.255.255.255',
    'BROADCAST_PORT': '39871',
    'WINTEST_SUBNET': '255.0.0.0',
    'TELEGRAM_TOKEN': '123:TESTTOKEN',
    'MAGIC_KEY': 'secret',
    'SUPER_USER_KEY': 'super-secret',
    'DEFAULT_LANG': 'en',
    'LANGUAGEPACK_PATH': os.path.join(ROOT, 'lang') + os.sep,
    'LOG_FILE_PATH': os.path.join(TMP, 'wttgbot.log'),
    'DATABASE_FILE_PATH': os.path.join(TMP, 'wttgbot.json'),
    'FILE_LOGGING_LEVEL': 'DEBUG',
    'CONSOLE_LOGGING_LEVEL': 'CRITICAL',
    'KEEP_N_OLD_LOGS': '2',
    'WT_STN_LIMIT': '10',
    'WT_MSG_LIMIT': '79',
    'WT_CALL_PREFIX': '',
    'WT_CALL_SUFFIX': '/TG',
    'WT_WD_TIMEOUT': '120',
    'TG_CONFIRM_DEFAULT': 'True',
})

import BOTConfiguration as cf # noqa: E402


@pytest.fixture
def fresh_db():
    ''' Empty in-memory database for a test, restored afterwards '''
    oldChats, oldUsers = dict(cf.chats), dict(cf.users)
    cf.chats.clear()
    cf.users.clear()
    yield cf
    cf.chats.clear()
    cf.users.clear()
    cf.chats.update(oldChats)
    cf.users.update(oldUsers)
