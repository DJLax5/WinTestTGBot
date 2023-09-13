import config as cf
import logging, socket, re
import os, threading
import numpy as np
from enum import Enum


class WinTestHandler:
    ''' This class provides the handling of wintest messages. '''

    class OP_CHANGE(Enum):
        LOGOFF = 0
        LOGIN = 1

    class InvalidStationLength(Exception):
        ''' Raised when it's tried to send a message with a invalid station length '''
        pass

    class InvalidMessageLength(Exception):
        ''' Raised when it's tried to send a message with a invalid message length '''
        pass

    

    def __init__(self, newMessageHandler, opChangeHandler):
        self.newMessageHandler = newMessageHandler
        self.opChangeHandler = opChangeHandler 
        self._stop_event = False
        self._running = False
        self.thread = None


    def start(self):
        self._stop_event = False
        if self._running == False:
            self.thread = threading.Thread(target=self.listen)
            self.thread.start()

    def stop(self):
        self._stop_event = True
        cf.log.debug('[WT] Stop event')
        try:
            self.thread.join(timeout=5)
        except:
            pass # We really don't care, if this thread really closed gracefully to be honest. 

    def listen(self):
        cf.log.info('[WT] WinTest Listening started')
        self._running = True


        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
        sock.bind((self.ip, os.getenv('BORADCAST_PORT')))

        while self._stop_event == False:
            data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
            print("received message: %s" % data)
        sock.shutdown()
        sock.close()
        self._stop_event = False
        self._running = False
        cf.log.info('[WT] WinTest Listening stopped')

    def __del__(self):
        self.stop()

    def sendToWT(self, source, message):
        ''' InvalidStationLength, InvalidMessageLength, Raises UnicodeEncodeError '''

        if len(source) > os.getenv('WT_STN_LIMIT'):
            raise WinTestHandler.InvalidStationLength()
        if len(source) > os.getenv('WT_MSG_LIMIT'):
            raise WinTestHandler.InvalidMessageLength()
        message = message.replace('"', '\\"')
        message = message.replace('\\', '\\\\')
        message = message.replace('€', '\\200')

        source = source.replace('"', '\\"')
        source = source.replace('\\', '\\\\')
        source = source.replace('€', '\\200')

        cmd = 'GAB: "' + source + '" "" "' + message + '"'
        cmd = self.toUDPmsg(cmd)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
            sock.sendto(cmd, (os.getenv('BRAODCAST_IP'),os.getenv('BRAODCAST_IP')))
        except Exception as e:
            cf.log.error('[WT] Could not send message! Reason: ' + str(e))



    @staticmethod
    def toUDPmsg(msg):
        encoded_string = ''
        for byte in msg.encode('iso-8859-1'):
            if byte > 127:
                encoded_string += "\\" + oct(byte)[2:].zfill(3)
            else:
                encoded_string += chr(byte)
        checksum = WinTestHandler.getChecksum(encoded_string)
        rbytes = bytearray(encoded_string.encode('ascii'))
        rbytes.append(checksum)
        rbytes.append(0)

        return bytes(rbytes)
    
    @staticmethod
    def getChecksum(msg):
        checksum = 0   

        for byte in msg.encode('ascii'):
            checksum += byte
            
        checksum |= 128
        checksum %= 256

        return checksum
        