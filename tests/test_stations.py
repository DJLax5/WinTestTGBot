import os, time, threading, json, logging
from types import SimpleNamespace
import pytest
import BOTConfiguration as cf
from WinTestTGBot import WinTestTGBot
from test_telegram import fake_update, ctx, run_async, tcm # noqa: F401


def make_bot(path):
    ''' A WinTestTGBot without network parts, only the station bookkeeping '''
    bot = WinTestTGBot.__new__(WinTestTGBot)
    bot.stations, bot._stationsUpdated, bot._stationsLock, bot._stationsPath = {}, 0.0, threading.Lock(), path
    bot.tcm = SimpleNamespace(sendMessage=lambda *a, **k: None)
    bot.wt = SimpleNamespace(wdFlag=False)
    return bot


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / 'wtstations.json')


def test_persist_and_restore(path):
    bot = make_bot(path)
    bot.opChangeOnStation('RUN1', 'DL1ABC')
    bot.opChangeOnStation('MULT')
    data = json.load(open(path))
    assert data['stations'] == {'RUN1': 'DL1ABC', 'MULT': ''} and abs(data['updated'] - time.time()) < 5
    fresh = make_bot(path)
    fresh.loadStations()
    assert fresh.stations == {'RUN1': 'DL1ABC', 'MULT': ''} and fresh.getOPs() == ['DL1ABC']
    assert fresh.stationsText() == 'MULT: -\nRUN1: DL1ABC'
    assert fresh.getDataDump() == {'wt_heartbeat': True, 'stations': 'MULT: -\nRUN1: DL1ABC\n'}
    assert fresh.getStations()[1].endswith('UTC')


def test_old_state_is_ignored(path, monkeypatch):
    bot = make_bot(path)
    bot.opChangeOnStation('RUN1', 'DL1ABC')
    data = json.load(open(path))
    data['updated'] = time.time() - 49 * 3600
    json.dump(data, open(path, 'w'))
    fresh = make_bot(path)
    fresh.loadStations()
    assert fresh.stations == {}
    monkeypatch.setenv('WT_STATIONS_MAX_AGE', str(100 * 3600))
    fresh.loadStations()
    assert fresh.stations == {'RUN1': 'DL1ABC'}


def test_missing_or_broken_file(path):
    bot = make_bot(path)
    bot.loadStations()
    assert bot.stations == {}
    open(path, 'w').write('garbage')
    bot.loadStations()
    assert bot.stations == {}
    assert bot.getStations() == ({}, '')


def test_incoming_message_uses_snapshot_and_ops(path, fresh_db):
    bot = make_bot(path)
    sent = []
    bot.tcm = SimpleNamespace(sendMessage=lambda chat, msg, header='': sent.append((chat, msg, header)))
    cf.newPrivateChat('alice', '1', wt_dispname='DL1ABC')
    cf.updateChat('1', 'valid', True) # mute 'own' by default
    cf.newPrivateChat('bob', '2', wt_dispname='DL2XYZ')
    cf.updateChat('2', 'valid', True)
    cf.newPrivateChat('carol', '3')
    cf.chats['3']['user'] = 'ghost' # broken reference must not raise
    cf.updateChat('3', 'valid', True)
    cf.newChat('-4', is_private=False, groupname='g', mute='all')
    cf.updateChat('-4', 'valid', True)
    bot.opChangeOnStation('RUN1', 'dl1abc')
    bot.incomingWTMessage('RUN1', 'cq test')
    bot.incomingWTMessage('NEW', 'hello')
    assert sent == [('2', 'cq test', 'RUN1 / dl1abc'), ('3', 'cq test', 'RUN1 / dl1abc'), # alice operates and is muted
                    ('2', 'hello', 'NEW'), ('3', 'hello', 'NEW')]
    assert bot.stations['NEW'] == ''


def test_ops_and_setop_commands(tcm, fresh_db, path):
    bot = make_bot(path)
    tcm.setOP, tcm.getStations = bot.opChangeOnStation, bot.getStations
    up = fake_update(10, user_id=10, username='su')
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    run_async(tcm, tcm.handleOps(up, ctx()))
    assert 'not seen' in up.effective_message.replies[-1][0]
    run_async(tcm, tcm.handleSetop(up, ctx('RUN1', 'dl1abc')))
    assert 'super' in up.effective_message.replies[-1][0] and bot.stations == {}
    cf.updateUser('su', 'is_superuser', True)
    run_async(tcm, tcm.handleSetop(up, ctx('RUN1', 'dl1abc')))
    assert bot.stations == {'RUN1': 'DL1ABC'}
    run_async(tcm, tcm.handleSetop(up, ctx('run1')))
    assert bot.stations == {'RUN1': ''} and 'no operator' in up.effective_message.replies[-1][0]
    run_async(tcm, tcm.handleSetop(up, ctx()))
    assert '/setop' in up.effective_message.replies[-1][0]
    bot.opChangeOnStation('MULT', 'DL2XYZ')
    run_async(tcm, tcm.handleOps(up, ctx()))
    text = up.effective_message.replies[-1][0]
    assert 'MULT: DL2XYZ' in text and 'RUN1: \\-' in text and 'UTC' in text
    run_async(tcm, tcm.handleHelp(up, ctx()))
    assert '/setop' in up.effective_message.replies[-1][0]


def test_op_is_only_at_one_station(path):
    bot = make_bot(path)
    bot.opChangeOnStation('RUN1', 'DL1ABC')
    bot.opChangeOnStation('MULT', 'DL2XYZ')
    bot.opChangeOnStation('RUN2', 'dl1abc') # no LOGOUT from RUN1 by Win-Test
    assert bot.stations == {'RUN1': '', 'MULT': 'DL2XYZ', 'RUN2': 'dl1abc'} and bot.getOPs() == ['DL2XYZ', 'DL1ABC']
    assert json.load(open(path))['stations'] == bot.stations
    bot.opChangeOnStation('RUN2', 'dl1abc') # relogin at the same station
    bot.opChangeOnStation('RUN1', 'DL2XYZ')
    assert bot.stations == {'RUN1': 'DL2XYZ', 'MULT': '', 'RUN2': 'dl1abc'}
    bot.opChangeOnStation('RUN2')
    assert bot.getOPs() == ['DL2XYZ']


def test_setop_moves_op_without_ml_warnings(tcm, fresh_db, path, caplog):
    caplog.set_level(logging.DEBUG, logger='BOTConfiguration')
    bot = make_bot(path)
    tcm.setOP, tcm.getStations = bot.opChangeOnStation, bot.getStations
    up = fake_update(11, user_id=11, username='su2')
    run_async(tcm, tcm.handleStart(up, ctx()))
    run_async(tcm, tcm.handleVerify(up, ctx('secret')))
    cf.updateUser('su2', 'is_superuser', True)
    run_async(tcm, tcm.handleSetop(up, ctx('RUN1', 'dl1abc')))
    run_async(tcm, tcm.handleSetop(up, ctx('MULT', 'DL1ABC')))
    assert bot.stations == {'RUN1': '', 'MULT': 'DL1ABC'}
    run_async(tcm, tcm.handleSetop(up, ctx('MULT')))
    assert bot.stations == {'RUN1': '', 'MULT': ''}
    assert not [r for r in caplog.records if '[ML]' in r.getMessage()]


def test_rejected_user_input_is_not_a_warning(path, caplog):
    from WinTestHandler import WinTestHandler
    caplog.set_level(logging.DEBUG, logger='BOTConfiguration')
    bot = make_bot(path)
    def send(origin, msg):
        if len(msg) > 79:
            raise WinTestHandler.InvalidMessageLengthException()
        msg.encode('cp1252')
    bot.wt = SimpleNamespace(wdFlag=False, sendToWT=send)
    assert bot.publishMessage('DL1ABC/TG', 'x' * 80) == 2
    assert bot.publishMessage('DL1ABC/TG', '\U0001F600') == 1
    assert bot.publishMessage('DL1ABC/TG', 'ok') == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert '80 > 79' in caplog.text
