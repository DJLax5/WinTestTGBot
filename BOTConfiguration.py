''' This file provides the configuration for this bot. This includes the logging functionality, multilanguage support and database handling.'''
# Imports
import os, sys
from dotenv import load_dotenv
load_dotenv() # load the .env keys
import logging
import json, re, datetime, threading
from MuliLanguageMessages import MulitLanguageMessages


class TelegramLoggingHandler(logging.Handler):
        ''' An class which provides the handler to also send messages to telegram. '''
        def __init__(self, chat_id,level = 40) -> None:
            '''Store the target chat_id and log level for this instance'''
            super().__init__()
            self.chat_id = chat_id
            try:
                self.level = int(level) # try to get the level, revert to 'ERROR' if it fails
            except:
                self.level = 40
                log.error('[TLH] Could not determine the logging-level for telegram messages. Default: ERROR')
            log.debug('[TLH] New logging handler activated.')

        def updateLevel(self, newlevel):
            ''' Provides a functionality to update the logging level'''
            try:
                self.level = int(newlevel) # try to get the level, revert to 'ERROR' if it fails
            except:
                self.level = 40
                log.error('[TLH] Could not determine the logging-level for telegram messages. Default: ERROR')
            log.debug('[TLH] Logging level updated to '+ str(newlevel))

        def emit(self, record):
            ''' The function which is called on each logging event, passes the logging event to telegram using the handler which is set up by the main script'''
            if 'cannot schedule new futures after shutdown' in record.message: # we're logging recursive execptions, and we're probably the cause of it. break the loop!
                return
            if record.levelno >= self.level: # record passed the threshold
                try:
                    messageLogCallback(self.chat_id,'\U0001F6A7 LOGGING EVENT \U0001F6A7 \n[' + record.levelname + '] ' + record.message)
                except: # this exception is not needed, the error is logged anyways
                    pass


def loadDatabase():
    ''' Function used to load the userdata'''
    
    # load the json data
    try:
        os.makedirs(os.path.dirname(os.getenv('DATABASE_FILE_PATH')), exist_ok=True) # on first start, make sure all the paths are ok
        with open(os.getenv('DATABASE_FILE_PATH')) as f:
            data = json.loads(f.read())
        if data.get('chats') != None and data.get('users') != None: # check the format
            log.info('[CONFIG] Confdiguration found and loaded')
            return data['chats'], data['users']
        else:
            log.warning('[CONFIG] The user data is not present. If this is the first start of the bot, this is expected.')
            return {}, {}
    except Exception as e:
        log.warning('[CONFIG] The user data is not present. If this is the first start of the bot, this is expected.')
        return {}, {}

def storeDatabase():
    ''' Function to store updates to the database on the harddrive. '''
    try:
        data = {}
        data['users'] = users
        data['chats'] = chats
        with open(os.getenv('DATABASE_FILE_PATH'), 'w') as f:
            f.write(json.dumps(data))
        log.debug('[CONFIG] Database file updated.')
    except Exception as e:
        log.error('[CONFIG] Writing data file failed. Reason: ' + str(e))

def checkDatabase(chats, users, modified = False):
    ''' Check the database integity. Also good to insert new attributes into existing instances after an update. '''    
    for chat in chats:
        if chats[chat].get('langcode') == None:
            chats[chat]['langcode'] = os.getenv('DEFAULT_LANG')
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing langcode. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('valid') == None:
            chats[chat]['valid'] = False
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing validation. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('is_private') == None:
            chats.pop(chat)
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing private tag. Deleting this chat.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('mute') == None:
            chats[chat]['mute'] = 'none' if chats[chat]['is_private'] == False else 'own'
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing mute tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('user') == None:
            chats[chat]['user'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing user tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        elif chats[chat]['user'] != '' and users.get(chats[chat]['user']) == None:
            chats[chat]['user'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, referenced user non existing. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('wt_confirm') == None:
            chats[chat]['wt_confirm'] = True
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing wt_confirm tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('tg_to_tg') == None:
            chats[chat]['tg_to_tg'] = True
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing tg_to_tg tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
        
        if chats[chat].get('groupname') == None:
            chats[chat]['groupname'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing groupname tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            

    for user in users:
        if users[user].get('wt_dispname') == None:
            users[user]['wt_dispname'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing wt_dispname tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if users[user].get('chat_id') == None:
            users[user]['chat_id'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing chat_id tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        elif users[user]['chat_id'] != '' and chats.get(users[user]['chat_id']) == None:
            users[user]['chat_id'] = ''
            modified = True
            log.warning('[CONFIG] Database integretry compromised, user is referncing non-existing chat. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if users[user].get('log_level') == None:
            users[user]['log_level'] = 'none'
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing log_level tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if users[user].get('is_superuser') == None:
            users[user]['is_superuser'] = False
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing is_superuser tag. Restoring to default.')
            return checkDatabase(chats, users, modified)           

    return chats, users, modified

        
        

def setupLogging():
    ''' Sets up the logger, handles log files and different log levels for different handlers '''
    # Set up the logger with file and console handlers
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Create a console handler and set its level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(os.getenv('CONSOLE_LOGGING_LEVEL'))
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    # handle old logfiles
    logdir = os.path.dirname(os.getenv('LOG_FILE_PATH'))
    basename = os.path.basename(os.getenv('LOG_FILE_PATH'))
    os.makedirs(logdir, exist_ok=True)
    pattern = r'^'+ basename + r'(?:.(\d+))?$'
    oldLogs = [filename for filename in os.listdir(logdir) if re.match(pattern, filename)] # get all old logs
    oldLogs = sorted(oldLogs,key=lambda name: int(re.match(pattern, name).group(1) if re.match(pattern, name).group(1) != None else 0)) # sort them by their number

    for oldfile in reversed(oldLogs):
        n = int(re.match(pattern, oldfile).group(1) if re.match(pattern, oldfile).group(1) != None else 0) # extract the number
        if n >= int(os.getenv('KEEP_N_OLD_LOGS')): # number exeeds the max number, delete
            os.remove(os.path.join(logdir, oldfile))
        else: # increment the number
            os.rename(os.path.join(logdir, oldfile),os.getenv('LOG_FILE_PATH') + '.' + str(n+1))
        
    # Create a file handler and set its level 
    f = open(os.getenv('LOG_FILE_PATH'), "w", encoding='utf-8')
    f.write('Win-Test Telegram Bot log file with Level: ' + os.getenv('FILE_LOGGING_LEVEL') + ', start time: ' + datetime.datetime.now().strftime('%d %b %Y, %H:%M:%S') + '\n')
    f.close()
    file_handler = logging.FileHandler(os.getenv('LOG_FILE_PATH'), mode='a', encoding='utf-8')
    file_handler.setLevel(os.getenv('FILE_LOGGING_LEVEL'))
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='[%d.%m.%y %H:%M:%S]'))

    # Add the handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


def newChat(chat_id, langcode=os.getenv('DEFAULT_LANG'), is_private=True, mute='own', user='', wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True'), tgTOtg=True, groupname = ''):
    ''' If a new chat is started, we append it here to the database '''

    if user != '' and not users.get(user):
        log.warning('[CONFIG] Trying to create a new chat referencing a non-existing user. This is invalid, resetting user reference. ')
        user = ''
    chats[chat_id] = {'langcode': langcode,
                           'valid' : False,
                           'mute' : mute,
                           'is_private' : is_private,
                           'user' : user,
                           'wt_confirm' : wt_confirm,
                           'tg_to_tg' : tgTOtg,
                           'groupname' : groupname}
    log.debug('[CONFIG] New chat added to database')
    storeDatabase()   

def newUser(username, wt_dispname = '', chat = '', log_level = 'none'):
    ''' Store all users interacting with the bot '''

    if chat != '' and not chats.get(chat):
        log.warning('[CONFIG] Trying to create a new user referencing a non-existing chat. This is invalid, resetting chat reference. ')
        chat = ''
    users[username] = {'wt_dispname' : wt_dispname,
                            'chat_id' : chat,
                            'log_level' : log_level,
                            'is_superuser' : False}
    log.info('[CONFIG] New user added to database')
    storeDatabase()

def newPrivateChat(username, chat_id, langcode=os.getenv('DEFAULT_LANG'), mute='own', wt_dispname = '', log_level = 'none', wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True'), tgTOtg=True):
    ''' A private chat always consists of a chat-user pair cross referencing eachother. For this, we provide this function'''
    users[username] = {'wt_dispname' : wt_dispname,
                            'chat_id' : chat_id,
                            'log_level' : log_level,
                            'is_superuser' : False}
    chats[chat_id] = {'langcode': langcode,
                           'valid' : False,
                           'mute' : mute,
                           'is_private' : True,
                           'user' : username,
                           'wt_confirm' : wt_confirm,
                           'tg_to_tg' : tgTOtg,
                           'groupname' : ''}
    log.info('[CONFIG] New chat-user pair added to database')
    storeDatabase()

def remove(chat):
    ''' Removes data from a chat. If the chat is private, also all user data is deleted.'''
    if chats.get(chat) == None:
        log.error('[CONFIG] Chat to be deleted does not exist!')
        return

    if chats[chat]['is_private'] == True:
        user = chats[chat]['user']
        log.info('[CONFIG] User ' + user + ' was removed.')
        users.pop(user)
    chats.pop(chat)
    log.info('[CONFIG] Chat was removed.')
    storeDatabase()

def removeUser(user):
    ''' Deletes a specific user. If this user has a private chat, this one is deleted aswell. '''
    if users.get(user) == None:
        log.error('[CONFIG] User to be deleted does not exist!')
        return
    
    if users[user]['chat_id'] != '':
        remove(users[user]['chat_id'])
    else:
        log.info('[CONFIG] User ' + user + ' was removed.')
        users.pop(user)
        storeDatabase()

def updateUser(user, key, value):
    ''' Update a specific user key-value pair. Not to be used for the logging level '''
    if users.get(user) == None:
        log.error('[CONFIG] Unable to find user ' + user)
        return
    if key == 'log_level':
        log.error('[CONFIG] Tried to set logging level via the update User Handler. This is not valid. Aborting.')
        return
    users[user][key] = value
    log.debug('[CONFIG] User ' + user + ' got updated: ' + key + ' to ' + str(value))
    storeDatabase()

def updateChat(chat, key, value):
    ''' Update a specific chat key-value pair.'''
    if chats.get(chat) == None:
        log.error('[CONFIG] Unable to find chat ' + chat)
        return
    chats[chat][key] = value
    log.debug('[CONFIG] A Chat got updated: ' + key + ' to ' + str(value))
    storeDatabase()

def updateUserLogging(user, loglevel, updateDatabase = True):
    ''' Update function for the user logging handler. In order to remove a logging handler set loglevel to 'none' '''
    if users.get(user) == None:
        log.error('[CONFIG] Trying to set a logging handler for a non-existent user ' + user)
        return -1
    
    if telegramLogHandlers.get(user) == None and loglevel.lower() != 'none': # we'll need to create a new handler
        try:
            ilevel = int(logging.getLevelName(loglevel.upper()))
        except:
            log.warning('[CONFIG] Unable to compute log level.')
            return -1
        telegramLogHandlers[user] = TelegramLoggingHandler(users[user]['chat_id'], ilevel)
        log.addHandler(telegramLogHandlers[user])
        log.info('[CONFIG] Logging handler added for user ' + user)
    elif telegramLogHandlers.get(user) != None:
        if loglevel.lower() == 'none':
            log.removeHandler(telegramLogHandlers[user])
            telegramLogHandlers.pop(user)
            log.info('[CONFIG] Logging handler removed for user ' + user)
        else:
            try:
                ilevel = int(logging.getLevelName(loglevel.upper()))
            except:
                log.warning('[CONFIG] Unable to compute log level.')
                return -1
            telegramLogHandlers[user].updateLevel(ilevel)
            log.info('[CONFIG] Logging handler for user ' + user + ' updated to ' + loglevel)
    if updateDatabase:
        users[user]['log_level'] = loglevel
        storeDatabase()
    return 0

def setupTGHandlers():
    ''' After the user data is present, setup logging handlers from previous runs '''
    for user in users:
        if users[user]['is_superuser'] == True and users[user]['log_level'] != 'none':
            updateUserLogging(user,users[user]['log_level'], updateDatabase=False)

def handleUncaughtException(exc_type, exc_value, exc_traceback):
    ''' Generic handler for all uncaught exceptions '''
    try:
        if issubclass(exc_type, KeyboardInterrupt): # let the KeyboardInterrupt Exception pass
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
    except:
        pass
    log.critical("[SYS] An uncaught exception occurred:", exc_info=(exc_type, exc_value, exc_traceback))


# Run the confiuration, will be executed on first import, only once
# Logging
messageLogCallback = None # This needs to be set bevor initializing the Telegram logging handlers
telegramLogHandlers = {} # Store the handlers 
log = setupLogging()
sys.excepthook = handleUncaughtException # store generic exception handler
threading.excepthook = handleUncaughtException
# Database
chats, users = loadDatabase()
chats, users, modified = checkDatabase(chats, users)
if modified:
    storeDatabase()

del modified # free-up namespace, no longer needed

# Multiple Languages:
ml = MulitLanguageMessages(log) # load languages
if not ml.languageSupported(os.getenv('DEFAULT_LANG')):
    log.fatal('[CONFIG] The default language has no associated languagepack. Cannot operate this way.')
    quit()

log.info('[CONFIG] Sucessfully started the system configuration. Interpreter Version: ' + sys.version)