import BOTConfiguration as cf
from WinTestHandler import WinTestHandler
from TelegramChatManager import TelegramChatManager
import os, time, threading

class WinTestTGBot:
    ''' The Main bot class. Use this to start the bot. '''

    stations = {} # keep track of the stations and who is currently op where

    def __init__(self):
        ''' Initialize the bot, setup all pipelines '''

        try:
            self.wt = WinTestHandler(self.incomingWTMessage, self.opChangeOnStation)  
        except WinTestHandler.IPNotFoundException as e: # This error is catastropic, shutdown
            quit()

        self.defaultLang = os.getenv('DEFAULT_LANG')
        self.wtBOTname = cf.ml.getMessage(self.defaultLang, 'BOT_STATION')

        self.tcm = TelegramChatManager(self.publishMessage, self.getOPs, self.getDataDump)

        # Now as the TelegramChatManager exists successfully, give its message handler to the telegram logging handlers
        cf.messageLogCallback = self.tcm.sendMessage
        cf.setupTGHandlers() 

        self._stop_event = False
        cf.log.info('[BOT] Bot initialized.')

    def start(self):
        ''' Start the WT Handler and the TCM '''

        if not self.wt.start():
            self.log.fatal('[BOT] Could not start WinTestHandler')
            return False
        
        self.tcm.start() # start the telegram polling      
        try:
            while self.wt.wdFlag == True: # wait until we got a heartbeat from wintest,
                time.sleep(0.1)
        except KeyboardInterrupt: # Need a escape option, if wintest does not send messages
            self.stop()
            return False
        
        # Now make the bot tell WinTest it's present
        try:
            self.wt.sendToWT(self.wtBOTname, cf.ml.getMessage(self.defaultLang, 'WT_BOOT_MSG'))
        except UnicodeEncodeError as e: # There are exception, just put them into the log and be done with them
            cf.log.error('[BOT] Cannot send power-up message to WT, Encode Error!')
        except WinTestHandler.InvalidMessageLengthException as lm:
            cf.log.error('[BOT] Cannot send power-up message to WT, Message Length Error!')
        except WinTestHandler.InvalidStationLengthException as ls:        
            cf.log.error('[BOT] Cannot send power-up message to WT, Station Length Error!')

        cf.log.info('[BOT] Bot started successfully.')
        return True

    def stop(self):
        ''' Top-level stop function. This will gracefully stop all threads and handlers '''
        self._stop_event = True
        self.tcm.stop()
        # Stop the WinTest Handler, send a goodbye message
        if self.wt.running:
            try:
                self.wt.sendToWT(self.wtBOTname,cf.ml.getMessage(self.defaultLang, 'WT_SHUTDOWN_MSG'))
            except UnicodeEncodeError as e: # There are exception, just put them into the log and be done with them
                cf.log.error('[BOT] Cannot send power-downm message to WT, Encode Error!')
            except WinTestHandler.InvalidMessageLengthException as lm:
                cf.log.error('[BOT] Cannot send power-down message to WT, Message Length Error!')
            except WinTestHandler.InvalidStationLengthException as ls:        
                cf.log.error('[BOT] Cannot send power-down message to WT, Station Length Error!')
            self.wt.stop()
        cf.log.info('[BOT] Bot stopped. Bye.')


    def incomingWTMessage(self, station, message):
        ''' If a WinTest Chat Message was captured, and parsed, handle it. '''
        chat_msg = '<b>' + station + ((' / ' + self.stations[station]) if self.stations.get(station) else '') + '<b>'
        chat_msg += ':\n'
        chat_msg += message
        
        if not self.stations.get(station): # we don't know this station yet. Treat it with no operators.
            self.opChangeOnStation(station)

        count = 0
        # go over each chat
        for chat in cf.chats:

            if cf.chats[chat]['valid'] == False: # skip uinvalid chats
                continue
            # All unmuted chats and chats which are not the current operator get notified
            if cf.chats[chat]['mute'] == 'none':
                self.tcm.sendMessage(chat, chat_msg)
                count += 1 
            elif cf.chats[chat]['is_private'] == True and cf.chats[chat]['mute'] == 'own':
                if not (cf.users[cf.chats[chat]['user']]['wt_dispname'].upper() in self.getOPs()): # filter if OPs requested not to receive messages:
                    self.tcm.sendMessage(chat, chat_msg) 
                    count += 1 
            
            if count == 5: # sending too many messages at once is not working. Just wait until we can send more! A more elegant solution may be implemented!
                time.sleep(5)
                count = 0 


    def opChangeOnStation(self, station, call=''):
        ''' If a OP-Change on a station was detected, mark it. To OP-OFF a station, leave the call empty.'''        
        self.stations[station] = call
        cf.log.debug('[BOT] Stations update: '+ str(self.stations))

    def publishMessage(self, origin, message):
        ''' Function to publish a message to Wintest. The return code encodes potential errors: 0 -> OK, 1 -> Encoding error, 2 -> Message too long, 3 -> Station too long'''
        try:
            message = message.replace('\n', ' ') # Discard newlines
            self.wt.sendToWT(origin,message)
            cf.log.info('[BOT] Message from ' + origin + ' sent to Win-Test: ' + message)
            return 0
        except UnicodeEncodeError as e: # There are exception, origin of this message
            cf.log.warning('[BOT] Message could not be sent, encoding error!')
            return 1
        except WinTestHandler.InvalidMessageLengthException as lm:
            cf.log.warning('[BOT] Message could not be sent, message too long!')
            return 2
        except WinTestHandler.InvalidStationLengthException as ls:       
            cf.log.warning('[BOT] Message could not be sent, station name too long!') 
            return 3
        
    def getOPs(self):
        ''' Extract the OPs which are currently logged in. '''
        ops = []
        for station in self.stations:
            if self.stations[station] != '':
                ops.append(self.stations[station].upper())
        return ops
    
    def getDataDump(self):
        ''' Dumps the current Win-Test state into a dict. (Heartbeat status and Staions/OPs) '''
        data_dump = {'wt_heartbeat':not self.wt.wdFlag}
        stationStr = ''
        for station in self.stations:
            stationStr += station
            if self.stations[station] != '':
                stationStr += ', OP: ' + self.stations[station]
            stationStr += '\n'
        data_dump['stations'] = stationStr
        return data_dump

class StopInterrupt(threading.Event):
    ''' A dummy event which will just wait. This allows to stay the start thread present.'''
    def wait(self, timeout=None):
        wait = super().wait  # get once, use often
        if timeout is None:            
            while not wait(0.1):  pass
        else:
            wait(timeout)


''' Main entry'''
if __name__ == '__main__':
    bot = WinTestTGBot() # create the bot
    if bot.start(): # try to start it
        # halt the main thread to be able to capture the Keyboard interrupt
        event = StopInterrupt()        
        try:
            event.wait()
        except KeyboardInterrupt:
            cf.log.info('[BOT] Keyboard Interrupt, shutting down')
            bot.stop() # Stop the bot gracefully
    else: # if the bot could not be started, stop everything
        cf.log.warning('[BOT] The bot did not start properly!')