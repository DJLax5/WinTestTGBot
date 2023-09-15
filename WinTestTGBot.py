import config as cf
from WinTestHandler import WinTestHandler
from TelegramChatManager import TelegramChatManager
import os, code, time, threading, sys

class WinTestTGBot:

    stations = {} # keep track of the stations and who is currently op where

    def __init__(self):
        ''' Initialize the bot, setup all pipelines '''
        try:
            self.wt = WinTestHandler(self.incomingWTMessage, self.opChangeOnStation)  
        except WinTestHandler.IPNotFoundException as e: # This error is catastropic, shutdown
            quit()

        self.defaultLang = os.getenv('DEFAULT_LANG')
        self.wtBOTname = cf.ml.getMessage(self.defaultLang, 'BOT_STATION')

        self.tcm = TelegramChatManager(self.publishMessage)

        self._stop_event = False

    def start(self):
        ''' Start the WT Handler and the TCM '''

        if not self.wt.start():
            self.log.fatal('[BOT] Could not start WinTestHandler')
            return False
        
       

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

        self.tcm.start()

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


    def incomingWTMessage(self, station, message):
        ''' If a WinTest Chat Message was captured, and parsed, handle it. '''
        chat_msg = station + ((' / ' + self.stations[station]) if self.stations.get(station) else '')
        chat_msg += ':\n'
        chat_msg += message
        #for chatID in self.chats:
        self.tcm.sendMessage('402776996', chat_msg) 
        

    def opChangeOnStation(self, station, call=''):
        ''' If a OP-Change on a station was detected, mark it. To OP-OFF a station, leave the call empty.'''
        
        self.stations[station] = call
        cf.log.debug('[BOT] Stations update: '+ str(self.stations))

    def publishMessage(self, origin, message):
        try:
            self.wt.sendToWT(os.getenv('WT_CALL_PREFIX') + origin + os.getenv('WT_CALL_SUFFIX'),message)
        except UnicodeEncodeError as e: # There are exception, just put them into the log and be done with them
            pass
        except WinTestHandler.InvalidMessageLengthException as lm:
            pass
        except WinTestHandler.InvalidStationLengthException as ls:        
            pass

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
        cf.log.fatal('[BOT] The bot could not start correctly!')
        bot.stop() 