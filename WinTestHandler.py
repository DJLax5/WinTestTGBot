import BOTConfiguration as cf
import socket, re
import os, threading, time, ipaddress, select

class WinTestHandler:
    ''' This class provides the handling of wintest messages, reception and infusing the wintest network with additional messages. '''

    class InvalidStationLengthException(Exception):
        ''' Raised when it's tried to send a message with a invalid station length '''
        pass

    class InvalidMessageLengthException(Exception):
        ''' Raised when it's tried to send a message with a invalid message length '''
        pass

    class IPNotFoundException(Exception):
        ''' Raised when no local interface is within the Win-Test subnet '''
        pass

    # REGEX for the incoming messages
    GAB_REGEX = r'^GAB: "(.*)" "(.*)" "(.*)"$'
    LOG_REGEX = r'^LOG(IN|OUT): "([^"]*)" "([^"]*)"(?: "([^"]*)" "([^"]*)")?$'
    ESCAPE_REGEX = re.compile(r'\\(\\|"|[0-7]{3})')
    WT_CODEPAGE = 'cp1252' # Win-Test is a windows program, bytes > 127 follow the ANSI codepage
    RESTART_DELAY = 5 # seconds before the listener socket is recreated after a failure


    def __init__(self, newMessageHandler, opChangeHandler):
        '''  Constructor to setup the handler. '''
        self.newMessageHandler = newMessageHandler
        self.opChangeHandler = opChangeHandler
        # setup the flags
        self._stop_event = False
        self.running = False
        self._thread = None
        self._wdTherad = None
        self.wdFlag = False
        self._last_packet = 0.0
        self._ownMessages = [] # as we send our own messages to a broadcast IP, we will receive our own messages aswell. Use this list to filter incoming messages
        self.port = int(os.getenv('BROADCAST_PORT'))
        self.broadcast_ip = os.getenv('BROADCAST_IP')
        self.ip = self._findLocalIP(float(os.getenv('WT_IP_WAIT', '120')))

    def _findLocalIP(self, waitTime):
        ''' Find the IP of this machine which is within the Win-Test subnet. Retries for `waitTime` seconds, as the network may come up after this bot (autostart). '''
        broadcast_ip = ipaddress.IPv4Address(self.broadcast_ip)
        subnet_mask = ipaddress.IPv4Address(os.getenv('WINTEST_SUBNET'))
        network_address = int(broadcast_ip) & int(subnet_mask)
        cf.log.debug('[WT] Target Subnet: ' + str(broadcast_ip))
        startT = time.time()
        while True:
            candidates = []
            try:
                candidates += socket.gethostbyname_ex(socket.gethostname())[2]
            except OSError:
                pass
            try: # ask the routing table, linux often reports only 127.0.1.1 for the hostname
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.connect((str(broadcast_ip), self.port))
                    candidates.append(sock.getsockname()[0])
            except OSError:
                pass
            for ip_str in candidates:
                cf.log.debug('[WT] Assigned IP: ' + ip_str)
                if int(ipaddress.IPv4Address(ip_str)) & int(subnet_mask) == network_address:
                    cf.log.info('[WT] Found Network interface/ip to communicate with Win-Test, using ' + ip_str)
                    return ip_str
            if time.time() - startT > waitTime:
                break
            cf.log.warning('[WT] No ip address in the Win-Test subnet yet, waiting for the network...')
            time.sleep(10)
        cf.log.fatal('[WT] This machine has no ip address in the same subnet as Win-Test, unable to execute.')
        raise WinTestHandler.IPNotFoundException()

    def start(self):
        ''' Function to start the event loop, this will start listening to incoming packets. Returns True if the start was successfull, Flase otherwise '''
        self._stop_event = False
        if self.running == False:
            cf.log.debug('[WT] Start event')
            self._thread = threading.Thread(target=self.listen, daemon=True)
            self._thread.start()
            startT = time.time()
            while self.running == False:
                if time.time() - startT > 10:
                    cf.log.error('[WT] Network listener did not start within 10 seconds! Aborting.')
                    self.stop()
                    return False
                time.sleep(0.1)
            # Start the watchdog, set is as triggered
            self.wdFlag = True
            self._last_packet = 0.0
            self._wdTherad = threading.Thread(target=self.watchdog, daemon=True)
            self._wdTherad.start()
            return True
        return False

    def stop(self):
        ''' Function to stop the event loop, this will try to join the threads, this function may wait up to 7 sec. '''
        self._stop_event = True
        cf.log.debug('[WT] Stop event')
        for t in (self._wdTherad, self._thread):
            try:
                t.join(timeout=2 if t is self._wdTherad else 5)
            except Exception:
                pass

    def listen(self):
        ''' Listening thread function. Waits for incoming packets and calls the corresponding event handlers. A failing socket is recreated, a bad packet never stops the listener. Stopped by the stop() function. '''
        cf.log.info('[WT] Win-Test listening started')
        while not self._stop_event:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', self.port)) # broadcasts are only delivered to INADDR_ANY sockets on linux
                sock.setblocking(False)
                self.running = True
                while not self._stop_event:
                    ready, _, _ = select.select([sock], [], [], 1.0)
                    if not ready:
                        continue
                    data, addr = sock.recvfrom(4096)
                    try:
                        self._handlePacket(data)
                    except Exception as e:
                        cf.log.error('[WT] Failed to process packet %r: %r' % (data, e))
            except Exception as e:
                cf.log.error('[WT] Listener failed, restarting in %d s. Reason: %r' % (self.RESTART_DELAY, e))
                self.running = False
                for _ in range(self.RESTART_DELAY * 10):
                    if self._stop_event:
                        break
                    time.sleep(0.1)
            finally:
                if sock is not None:
                    sock.close()
        self.running = False
        cf.log.info('[WT] Win-Test listening stopped')

    def _handlePacket(self, data):
        ''' Validate and dispatch a single datagram '''
        cf.log.debug('[WT] Received message from Win-Test: %r' % data)
        if len(data) < 2 or data[-1] != 0: # The last byte is always the 0 byte
            cf.log.debug('[WT] Received message is not in the correct format. Maybe it\'s a DX Cluster message. ')
            return
        if data in self._ownMessages: # It's one of our own, ignore
            return
        payload = data[:-2]
        if self.getChecksum(payload) != data[-2]:
            cf.log.warning('[WT] Wrong checksum received!')
            return
        msg = payload.decode(self.WT_CODEPAGE, errors='replace')
        self._last_packet = time.time() # reset watchdog

        m = re.match(self.GAB_REGEX, msg)
        if m:
            station = self.deescapeWT(m.group(1))
            toStation = self.deescapeWT(m.group(2))
            if toStation != '': # keep private messages private
                return
            text = self.deescapeWT(m.group(3))
            if text != '': # ignore empty messages
                cf.log.info('[WT] Message received from station ' + station + ': ' + text)
                self.newMessageHandler(station, text)
            return

        m = re.match(self.LOG_REGEX, msg)
        if m:
            station = self.deescapeWT(m.group(2))
            if m.group(1) == 'IN':
                call = self.deescapeWT(m.group(4) or '')
                cf.log.info('[WT] Login from station ' + station + ' from OP ' + call)
                self.opChangeHandler(station, call)
            else:
                cf.log.info('[WT] Logout from station ' + station)
                self.opChangeHandler(station)
        # We dont care about the other messages ... yet (?)

    def watchdog(self):
        ''' Simple watchdog which will alert when WT stops sending heartbeats'''
        while not self._stop_event:
            if time.time() - self._last_packet > float(os.getenv('WT_WD_TIMEOUT')):
                if self.wdFlag == False:
                    cf.log.warning('[WT] Watchdog timeout! Win-Test heartbeat missing!')
                    self.wdFlag = True
            elif self.wdFlag == True:
                self.wdFlag = False
                cf.log.info('[WT] Got Win-Test heartbeat')
            time.sleep(1)
        self.wdFlag = False

    def sendToWT(self, source, message):
        ''' Function to send a message to Win-Test as a station `source`
        Raises:InvalidStationLengthException, InvalidMessageLengthException, UnicodeEncodeErrorException '''
        if len(source) > int(os.getenv('WT_STN_LIMIT')):
            raise WinTestHandler.InvalidStationLengthException()
        if len(message) > int(os.getenv('WT_MSG_LIMIT')):
            raise WinTestHandler.InvalidMessageLengthException()
        if message == '':
            return

        cmd = 'GAB: "' + self.escapeWT(source) + '" "" "' + self.escapeWT(message) + '"'
        cmd = self.toUDPmsg(cmd) # encode and append checksum
        self._ownMessages.append(cmd)
        while len(self._ownMessages) > 5:
            self._ownMessages.pop(0)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((self.ip, 0)) # leave via the Win-Test interface
                sock.sendto(cmd, (self.broadcast_ip, self.port))
        except Exception as e:
            cf.log.error('[WT] Could not send message! Reason: ' + str(e))

    @staticmethod
    def escapeWT(msg):
        ''' Function to escape the special Win-Test encoding scheme '''
        msg = msg.replace('\\', '\\\\')
        msg = msg.replace('"', '\\"')
        msg = msg.replace('\n', ' ')
        escaped_string = ''
        pos = 0
        for byte in msg.encode(WinTestHandler.WT_CODEPAGE): # this may raise an UnicodeEncodeError, this is expected
            if byte > 127:
                escaped_string += '\\' + oct(byte)[2:].zfill(3) # replace the character with the ascii sequence \OCT
            elif byte == 0:
                raise UnicodeEncodeError(WinTestHandler.WT_CODEPAGE, msg, pos, pos, 'Cannot encode the zero character!')
            else:
                escaped_string += chr(byte)
            pos += 1
        return escaped_string

    @staticmethod
    def deescapeWT(msg):
        ''' Function to de-escape the special Win-Test encoding scheme. Single left-to-right pass, so an escaped backslash followed by digits is not mistaken for an octal sequence. '''
        def replace(match):
            seq = match.group(1)
            if seq in ('\\', '"'):
                return seq
            return bytes([int(seq, 8) & 0xFF]).decode(WinTestHandler.WT_CODEPAGE, errors='replace')
        return WinTestHandler.ESCAPE_REGEX.sub(replace, msg)

    @staticmethod
    def toUDPmsg(msg):
        ''' Function which encodes the udp message into bytes and appends the checksum '''
        rbytes = bytearray(msg.encode('ascii'))
        rbytes.append(WinTestHandler.getChecksum(rbytes))
        rbytes.append(0)
        return bytes(rbytes)

    @staticmethod
    def getChecksum(msg):
        ''' Wintest checksum algorihm, it's ((sum of all bytes) | 128) % 256. Accepts str (ascii) or bytes. '''
        if isinstance(msg, str):
            msg = msg.encode('ascii')
        return (sum(msg) | 128) % 256
