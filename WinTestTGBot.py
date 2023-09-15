import config as cf
from WinTestHandler import WinTestHandler
import os, code, time, threading

class WinTestTGBot:

    stations = {}

    def __init__(self):
        self.wt = WinTestHandler(self.incomingWTMessage, self.opChangeOnStation)        
        self._stop_event = False

    def start(self):
        if not self.wt.start():
            self.log.fatal('[BOT] Could not start the WinTestHandler')
            return False

        try:
            while self.wt.wdFlag == True and self._stop_event == False:
                time.sleep(0.1)
            
            self.wt.sendToWT('TG BOT', 'Der Telegram Bot ist nun aktiv!') # TODO: Add the welcome message in the default language!

        except KeyboardInterrupt:
            self.stop()
            return False

        return True

    def stop(self):
        self._stop_event = True
        self.wt.sendToWT('TG BOT', 'Der Telegram Bot fährt herunter!') # TODO: Add the bye message in the default language!
        self.wt.stop()


    def incomingWTMessage(self, station, message):
        print(station, message)

    def opChangeOnStation(self, station, call=''):
        print(station, call)

class StopInterrupt(threading.Event):
    def wait(self, timeout=None):
        wait = super().wait  # get once, use often
        if timeout is None:            
            while not wait(0.01):  pass
        else:
            wait(timeout)

if __name__ == '__main__':
    bot = WinTestTGBot()
    if bot.start():    
        event = StopInterrupt()
        
        try:
            event.wait()
        except KeyboardInterrupt:
            cf.log.info('[BOT] Keyboard Interrupt, shutting down')
            bot.stop()
    else: 
        cf.log.warn('[BOT] The bot could not start correctly!')