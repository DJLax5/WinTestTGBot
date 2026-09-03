import socket, time, os
import pytest
from WinTestHandler import WinTestHandler as W

PORT = int(os.environ['BROADCAST_PORT'])


def test_escape_roundtrip():
    for text in ['Hello "World"', 'back\\slash', 'Gr\u00fc\u00dfe', '5 \u20ac', 'C:\\189 path', 'quote \\" mix']:
        assert W.deescapeWT(W.escapeWT(text)) == text


def test_escape_known_sequences():
    assert W.escapeWT('\u00fc') == '\\374'
    assert W.escapeWT('\u20ac') == '\\200' # euro is 0x80 in cp1252
    assert W.deescapeWT('\\200') == '\u20ac'
    assert W.escapeWT('a\nb') == 'a b'


def test_deescape_never_raises_on_bad_digits():
    assert W.deescapeWT('\\189') == '\\189'
    assert W.deescapeWT('\\777') == '\u00ff' # masked to one byte
    assert W.deescapeWT('\\\\189') == '\\189' # escaped backslash followed by digits stays literal


def test_escape_rejects_unencodable():
    with pytest.raises(UnicodeEncodeError):
        W.escapeWT('smile \U0001F600')
    with pytest.raises(UnicodeEncodeError):
        W.escapeWT('zero \x00')


def test_checksum_str_and_bytes():
    assert W.getChecksum('GAB: "A" "" "x"') == W.getChecksum(b'GAB: "A" "" "x"')
    dg = W.toUDPmsg('GAB: "A" "" "x"')
    assert dg[-1] == 0 and dg[-2] == W.getChecksum(dg[:-2])


class Recorder:
    def __init__(self):
        self.msgs, self.ops, self.raise_next = [], [], False

    def msg(self, station, text):
        if self.raise_next:
            self.raise_next = False
            raise RuntimeError('handler boom')
        self.msgs.append((station, text))

    def op(self, station, call=''):
        self.ops.append((station, call))


@pytest.fixture
def handler():
    rec = Recorder()
    wt = W(rec.msg, rec.op)
    assert wt.start()
    yield wt, rec
    wt.stop()
    assert not wt._thread.is_alive()


def send_raw(data):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, ('127.0.0.1', PORT))


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_listener_survives_garbage_and_parses(handler):
    wt, rec = handler
    send_raw(b'') # empty datagram
    send_raw(b'\xff\xfe\x00') # non ascii with zero terminator
    send_raw(b'GAB: "A" "" "x"\x00\x00') # wrong checksum
    send_raw(W.toUDPmsg('GAB: "STN" "" "\\189 bad octal"'))
    send_raw(W.toUDPmsg('GAB: "STN" "OTHER" "private"'))
    send_raw(W.toUDPmsg('LOGIN: "RUN1" "1" "DL1ABC" "x"'))
    send_raw(W.toUDPmsg('GAB: "RUN1" "" "Gr\\374\\337e"'))
    assert wait_for(lambda: len(rec.msgs) == 2)
    rec.raise_next = True
    send_raw(W.toUDPmsg('GAB: "RUN1" "" "handler raises"'))
    send_raw(W.toUDPmsg('GAB: "RUN1" "" "still alive"'))
    send_raw(W.toUDPmsg('LOGOUT: "RUN1" "1"'))
    assert wait_for(lambda: len(rec.ops) == 2)
    assert rec.ops == [('RUN1', 'DL1ABC'), ('RUN1', '')]
    assert rec.msgs == [('STN', '\\189 bad octal'), ('RUN1', 'Gr\u00fc\u00dfe'), ('RUN1', 'still alive')]
    assert wt.running and wt._thread.is_alive()
    assert wait_for(lambda: wt.wdFlag == False) # a valid packet counts as heartbeat


def test_own_broadcast_is_filtered(handler):
    wt, rec = handler
    wt.sendToWT('TG BOT', 'hello "all"')
    send_raw(W.toUDPmsg('GAB: "X" "" "marker"'))
    assert wait_for(lambda: len(rec.msgs) == 1)
    assert rec.msgs == [('X', 'marker')]


def test_send_limits():
    wt = W.__new__(W)
    with pytest.raises(W.InvalidStationLengthException):
        wt.sendToWT('X' * 11, 'msg')
    with pytest.raises(W.InvalidMessageLengthException):
        wt.sendToWT('X', 'm' * 80)
