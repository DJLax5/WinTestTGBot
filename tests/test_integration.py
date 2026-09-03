''' Start the whole bot (without touching Telegram) and drive it via UDP like Win-Test would. '''
import asyncio, socket, threading, time, os
from types import SimpleNamespace
import telegram
from telegram.ext import Application
import BOTConfiguration as cf
from WinTestHandler import WinTestHandler as W
from test_telegram import FakeBot, wait_for

PORT = int(os.environ['BROADCAST_PORT'])


def send_raw(data):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, ('127.0.0.1', PORT))


def test_full_start_relay_and_stop(monkeypatch, fresh_db, tmp_path):
    async def get_me(self):
        return SimpleNamespace(username='WinTestBot')
    monkeypatch.setattr(telegram.Bot, 'get_me', get_me)
    fake = FakeBot()

    def run_polling(self, **kwargs):
        ''' stand-in for Application.run_polling: run the loop with the send worker, like PTB does after its bootstrap '''
        assert kwargs.get('stop_signals') is None and kwargs.get('bootstrap_retries') == -1
        self.bot = fake
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.post_init(self))
        loop.run_forever()
        loop.run_until_complete(self.post_shutdown(self))
    monkeypatch.setattr(Application, 'run_polling', run_polling)
    monkeypatch.setenv('STATIONS_FILE_PATH', str(tmp_path / 'stations.json'))
    monkeypatch.setattr('TelegramChatManager.TelegramChatManager.CHAT_GAP_PRIVATE', 0.05)

    cf.newPrivateChat('su', '77', wt_dispname='DL9SU')
    cf.updateChat('77', 'valid', True)
    cf.updateChat('77', 'mute', 'none')
    cf.updateUser('su', 'is_superuser', True)
    cf.newPrivateChat('op', '88', wt_dispname='DL1ABC')
    cf.updateChat('88', 'valid', True) # mute 'own'

    from WinTestTGBot import WinTestTGBot
    bot = WinTestTGBot()
    heartbeat = threading.Thread(target=lambda: (time.sleep(0.3), send_raw(W.toUDPmsg('LOGIN: "RUN1" "1" "DL1ABC" "x"'))), daemon=True)
    heartbeat.start()
    assert bot.start() # blocks until the first Win-Test packet
    assert wait_for(lambda: bot.stations.get('RUN1') == 'DL1ABC')
    send_raw(W.toUDPmsg('GAB: "RUN1" "" "cq contest"'))
    assert wait_for(lambda: any('cq contest' in s[1] for s in fake.sent))
    chats = sorted(s[0] for s in fake.sent)
    assert '77' in chats and '88' not in chats # the operator himself is muted
    assert any('BOT_BOOT' != s[1] and 'active' in s[1] for s in fake.sent if s[0] == '77') # boot message to the super-user
    assert bot.tcm.username == 'WinTestBot'

    t0 = time.time()
    bot.stop()
    assert time.time() - t0 < 10
    assert not bot.wt.running and not bot.tcm._thread.is_alive()
    assert fake.sent[-1][0] == '77' and 'shutdown' in fake.sent[-1][1]
    assert os.path.exists(str(tmp_path / 'stations.json'))
