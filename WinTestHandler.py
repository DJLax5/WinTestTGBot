import config as cf
import logging, socket, re
import os, threading, time, ipaddress, select
import numpy as np
from enum import Enum


class WinTestHandler:
    ''' This class provides the handling of wintest messages, reception and infusing the wintest network with additional messages. '''

    class InvalidStationLengthException(Exception):
        ''' Raised when it's tried to send a message with a invalid station length '''
        pass

    class InvalidMessageLengthException(Exception):
        ''' Raised when it's tried to send a message with a invalid message length '''
        pass

    class IPNotFoundException(Exception):
        ''' Raised when it's tried to send a message with a invalid message length '''
        pass

    # REGEX for the incoming messages
    GAB_REGEX = r'^GAB: "(.*)" "(.*)" "(.*)"$'
    LOG_REGEX = r'^LOG(IN|OUT): "([^"]*)" "([^"]*)"(?: "([^"]*)" "([^"]*)")?$'


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
        # Find the IP of this machine which is within the WinTest Subnet
        hostname = socket.gethostname()
        ip_addresses = socket.gethostbyname_ex(hostname)[2]

        # Convert the broadcast IP and subnet mask to IPv4Address objects
        broadcast_ip = ipaddress.IPv4Address(os.getenv('BROADCAST_IP'))
        subnet_mask = ipaddress.IPv4Address(os.getenv('WINTEST_SUBNET'))
        network_address = int(broadcast_ip) & int(subnet_mask)

        # Check if each assigned IP is in the same subnet as the broadcast IP
        self.ip = ''
        for ip_str in ip_addresses:
            ip = ipaddress.ip_address(ip_str)
            if int(ip) & int(subnet_mask) == network_address:
                self.ip = ip_str
                cf.log.info('[WT] Found Network interface/ip to communicate with WinTest, using ' + ip_str)
    
        if self.ip == '':
            cf.log.fatal('[WT] This machine has no ip address in the same subnet as WinTest, unable to execute.')
            raise WinTestHandler.IPNotFoundException()

    def start(self):
        ''' Function to start the event loop, this will start listening to incoming packets. Returns True if the start was successfull, Flase otherwise '''
        self._stop_event = False
        if self.running == False:
            cf.log.debug('[WT] Start event')
            self._thread = threading.Thread(target=self.listen)
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
            self._wdTherad = threading.Thread(target=self.watchdog)
            self._wdTherad.start()
            return True
        return False

    def stop(self):
        ''' Function to stio the event loop, this will try to join the thread, this function may wait up to 7 sec. '''
        self._stop_event = True
        cf.log.debug('[WT] Stop event')
        try:
            self._wdTherad.join(timeout=2)
            self._thread.join(timeout=5) # If the wintest instance is closed, this will probably fail as we are still waiting for packets.. Not that much of an issue I think
        except:
            pass # We really don't care, if this thread really closed gracefully to be honest. 

    def listen(self):
        ''' Listening thread function. This will wait for incoming packets and call the corresponding event handlers. Stopped by the stop() function. '''
        cf.log.info('[WT] WinTest Listening started')
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
            sock.bind((self.ip, int(os.getenv('BROADCAST_PORT'))))
        except Exception as e:
            cf.log.fatal('[WT] Cannot listen to incoming messages! Aborting!')
            raise 
        finally:
            self._stop_event = False
            self.running = False

        sock.setblocking(0) # non-blocking performacne allows for gracefully shutdowns
        self.running = True

        try:
            while self._stop_event == False:
                ready, _, _ = select.select([sock], [], [], 1.0)  # 1-second timeout
                if ready:
                    data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
                    cf.log.debug("[WT] Received message: %s" % data)

                    if data in self._ownMessages: # It's one of our own, ignore
                        continue

                    # The last byte is always the 0 byte, check it
                    if data[-1] != 0:
                        cf.log.warn('[WT] Received message is not in the correct format!')
                        continue

                    # Extract message, expected checksum and received checksum
                    msg = data[:-2].decode('ascii')
                    expChecksum = self.getChecksum(msg)
                    chkSum = data[-2]
                    
                    # chek the sum
                    if expChecksum != chkSum:
                        cf.log.warn('[WT] Wrong checksum received!')
                        continue
                
                    # reset watchdog
                    self._last_packet = time.time()

                    # GAB Message
                    m = re.match(self.GAB_REGEX, msg)
                    if m:
                        station = self.deescapeWT(m.group(1))
                        text = self.deescapeWT(m.group(3))
                        cf.log.info('[WT] Message received from station ' + station + ': ' + text)
                        self.newMessageHandler(station, text)
                        
                    # LOGIN / LOGOFF Message
                    m = re.match(self.LOG_REGEX, msg)
                    if m:
                        station = self.deescapeWT(m.group(2))
                        if m.group(1) == 'IN':
                            call = self.deescapeWT(m.group(4))
                            cf.log.info('[WT] Login into station ' + station + ' from OP ' + call)
                            self.opChangeHandler(station, call)
                        else:
                            cf.log.info('[WT] Logoff from station ' + station)
                            self.opChangeHandler(station)

                    # We dont care about the other messages ... yet (?)
        except Exception as e:
            cf.log.error('[WT] An error occured while trying to read messages, reason: ' + str(e))
        finally:
            sock.close()
            self._stop_event = False
            self.running = False
        cf.log.info('[WT] WinTest Listening stopped')


    def watchdog(self):
        ''' Simple watchdog which will alert when WT stops sending Heartbeats'''

        while self.running:
            if time.time() - self._last_packet > float(os.getenv('WT_WD_TIMEOUT')):
                if self.wdFlag == False:
                    cf.log.warn('[WT] Watchdog timeout! WinTest Heartbeat missing!') # TODO: Maybe do more... 
                    self.wdFlag = True
            elif self.wdFlag == True:
                self.wdFlag = False
                cf.log.info('[WT] Got WinTest Heartbeat')
            time.sleep(1)
        self.wdFlag = False


    def sendToWT(self, source, message):
        ''' Function to send a message to WinTest as a station `source` 
        Raises:InvalidStationLengthException, InvalidMessageLengthException, UnicodeEncodeErrorException '''

        if len(source) > int(os.getenv('WT_STN_LIMIT')):
            raise WinTestHandler.InvalidStationLengthException()
        if len(source) > int(os.getenv('WT_MSG_LIMIT')):
            raise WinTestHandler.InvalidMessageLengthException()

        # Now escape special characters for wintest
        message = self.escapeWT(message)
        source = self.escapeWT(source)
        
        # build cmd
        cmd = 'GAB: "' + source + '" "" "' + message + '"'
        cmd = self.toUDPmsg(cmd) # encode and append checksum
        self._ownMessages.append(cmd)
        # Sendit
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
            sock.sendto(cmd, (os.getenv('BROADCAST_IP'),int(os.getenv('BROADCAST_PORT'))))
            
        except Exception as e:
            cf.log.error('[WT] Could not send message! Reason: ' + str(e))

    @staticmethod
    def escapeWT(msg):
        ''' Function to escape the special WinTest encoding scheme '''
        # First handle special characters
        msg = msg.replace('\\', '\\\\')
        msg = msg.replace('"', '\\"')
        msg = msg.replace('€', '\\200')
        escaped_string = ''
        # now encode it latin 1 and find the special characters
        pos = 0
        for byte in msg.encode('iso-8859-1'): # this may raise an UnicodeEncodeError, this is expected
            if byte > 127:
                escaped_string += "\\" + oct(byte)[2:].zfill(3) # replace the character with the ascii sequence \\OCT 
            elif byte == 0:
                raise UnicodeEncodeError('iso-8859-1', msg, pos, pos, 'Cannot encode the zero character!')
            else:
                escaped_string += chr(byte)
            pos += 1
        return escaped_string

    @staticmethod
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

        msg = re.sub(r'\\(\d{3})', replace_octal_num, msg) # replace all occurences
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
        