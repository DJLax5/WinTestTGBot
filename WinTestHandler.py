import config as cf
import logging, socket, re
import os, threading, time
import numpy as np
from enum import Enum


class WinTestHandler:
    ''' This class provides the handling of wintest messages. '''

    class OP_CHANGE(Enum):
        ''' Enumerator to indicate LOGIN / LOGOFF Events '''
        LOGOFF = 0
        LOGIN = 1

    class InvalidStationLength(Exception):
        ''' Raised when it's tried to send a message with a invalid station length '''
        pass

    class InvalidMessageLength(Exception):
        ''' Raised when it's tried to send a message with a invalid message length '''
        pass

    

    def __init__(self, newMessageHandler, opChangeHandler):
        '''  Constructor to setup the handler. '''
        self.newMessageHandler = newMessageHandler
        self.opChangeHandler = opChangeHandler 
        self._stop_event = False
        self._running = False
        self.thread = None
        self.whatchdog = None
        self._last_packet = time.time()
        # TODO: Find the correct IP for RX (Interface search!)


    def start(self):
        ''' Function to start the event loop, this will start listening to incoming packets. Returns True if the start was successfull, Flase otherwise '''
        self._stop_event = False
        if self._running == False:
            cf.log.debug('[WT] Start event')
            self.thread = threading.Thread(target=self.listen)
            self.thread.start()
            # TODO: Start Watchdog
            return True
        return False

    def stop(self):
        ''' Function to stio the event loop, this will try to join the thread, this function may wait up to 5 sec. '''
        self._stop_event = True
        cf.log.debug('[WT] Stop event')
        try:
            self.thread.join(timeout=5) # If the wintest instance is closed, this will probably fail as we are still waiting for packets.. Not that much of an issue I think
        except:
            pass # We really don't care, if this thread really closed gracefully to be honest. 

    def listen(self):
        ''' Listening thread function. This will wait for incoming packets and call the corresponding event handlers. Stopped by the stop() function. '''
        cf.log.info('[WT] WinTest Listening started')
        self._running = True


        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
        sock.bind((self.ip, os.getenv('BORADCAST_PORT')))

        while self._stop_event == False:
            data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
            cf.log.debug("[WT] Received message: %s" % data)
            self._last_packet = time.time()
            # TODO: Parse incoming messages
            # Regex for GAP: ^GAB: "(.*)" "(.*)" "(.*)"$
        sock.shutdown()
        sock.close()
        self._stop_event = False
        self._running = False
        cf.log.info('[WT] WinTest Listening stopped')

    def __del__(self):
        self.stop()

    def sendToWT(self, source, message):
        ''' Function to send a message to WinTest as a station `source` 
        Raises:InvalidStationLength, InvalidMessageLength, UnicodeEncodeError '''

        if len(source) > os.getenv('WT_STN_LIMIT'):
            raise WinTestHandler.InvalidStationLength()
        if len(source) > os.getenv('WT_MSG_LIMIT'):
            raise WinTestHandler.InvalidMessageLength()

        # Now escape special characters for wintest
        message = self.escapeWT(message)
        source = self.escapeWT(source)
        
        # build cmd
        cmd = 'GAB: "' + source + '" "" "' + message + '"'
        cmd = self.toUDPmsg(cmd) # encode and append checksum

        # Sendit
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
            sock.sendto(cmd, (os.getenv('BRAODCAST_IP'),os.getenv('BRAODCAST_IP')))
        except Exception as e:
            cf.log.error('[WT] Could not send message! Reason: ' + str(e))

    @staticmethod
    def escapeWT(msg):
        ''' Function to escape the special WinTest encoding scheme '''
        # First handle special characters
        msg = msg.replace('"', '\\"')
        msg = msg.replace('\\', '\\\\')
        msg = msg.replace('€', '\\200')
        escaped_string = ''
        # now encode it latin 1 and find the special characters
        for byte in msg.encode('iso-8859-1'): # this may raise an UnicodeEncodeError, this is expected
            if byte > 127:
                escaped_string += "\\" + oct(byte)[2:].zfill(3) # replace the character with the ascii sequence \\OCT 
            else:
                escaped_string += chr(byte)
        return escaped_string

    def deescapeWT(msg):
        ''' Function to de-escape the special WinTest encoding scheme '''

        # First replace the special characters
        msg = msg.replace('\\"', '"')
        msg = msg.replace('\\\\', '\\')
        msg = msg.replace('\\200', '€')
        
        # define the replacement scheme
        def replace_octal_num(match):
            octal_number = match.group(1) # number in octal representation after the \\
            char = chr(int(octal_number, 8)) # now encode this number into a character
            return char

        msg = re.sub(r'\\\\(\d{3})', replace_octal_num, msg) # replace all occurences
        return msg

    @staticmethod
    def toUDPmsg(msg):
        ''' Function which encodes the udp message into bytes and appends the checksum '''
        checksum = WinTestHandler.getChecksum(msg) 
        rbytes = bytearray(msg.encode('ascii'))
        rbytes.append(checksum)
        rbytes.append(0)

        return bytes(rbytes)
    
    @staticmethod
    def getChecksum(msg):
        ''' Wintest checksum algorihm, it's ((sum of all bytes) | 128) % 256 '''
        checksum = 0   

        for byte in msg.encode('ascii'):
            checksum += byte
            
        checksum |= 128
        checksum %= 256

        return checksum
        