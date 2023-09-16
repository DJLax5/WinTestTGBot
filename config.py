import os
from dotenv import load_dotenv
import logging
import json
from MuliLanguageMessages import MulitLanguageMessages

load_dotenv() # load the .env keys

def loadDatabase():
    """ Function used to load the userdata"""
    
    # load the json data
    try:
        os.makedirs(os.path.dirname(os.getenv('DATABASE_FILE_PATH')), exist_ok=True)
        with open(os.getenv('DATABASE_FILE_PATH')) as f:
            data = json.loads(f.read())
        if data.get('chats') != None and data.get('users') != None:
            return data['chats'], data['users']
        else:
            log.warn('[CONFIG] The user data is not present. If this is the first start of the bot, this is expected.')
            return {}, {}
    except Exception as e:
        log.warn('[CONFIG] The user data is not present. If this is the first start of the bot, this is expected.')
        return {}, {}

def storeDatabase():
    ''' Function to store updates to the database on the harddrive. '''
    try:
        data = {}
        data['users'] = users
        data['chats'] = chats
        with open(os.getenv('DATABASE_FILE_PATH'), 'w') as f:
            f.write(json.dumps(data))
        log.debug('[CONFIG] Database file written.')
    except Exception as e:
        log.error('[CONFIG] Writing data file failed. Reason: ' + str(e))


def setupLogging():
    # Set up the logger with file and console handlers
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Create a console handler and set its level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(os.getenv('CONSOLE_LOGGING_LEVEL'))
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    # Create a file handler and set its level 
    os.makedirs(os.path.dirname(os.getenv('LOG_FILE_PATH')), exist_ok=True)
    file_handler = logging.FileHandler(os.getenv('LOG_FILE_PATH'), mode='a')
    file_handler.setLevel(os.getenv('FILE_LOGGING_LEVEL'))
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='[%d.%m.%y %H:%M:%S]'))

    # Add the handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


def newChat(chat_id, langcode=os.getenv('DEFAULT_LANG'), is_private=True, mute='none', user='', wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True')):
    if user != '' and not users.get(user):
        log.warn('[CONFIG] Trying to create a new chat referencing a non-existing user. This is invalid, resetting user reference. ')
        user = ''
    chats[chat_id] = {'langcode': langcode,
                           'valid' : False,
                           'mute' : mute,
                           'is_private' : is_private,
                           'user' : user,
                           'wt_confirm' : wt_confirm}
    storeDatabase()

def newUser(username, wt_dispname = '', chat = '', log_level = os.getenv('DEFAULT_TELEGRAM_LOGGING_LEVEL')):
    if chat != '' and not chats.get(chat):
        log.warn('[CONFIG] Trying to create a new user referencing a non-existing chat. This is invalid, resetting chat reference. ')
        chat = ''
    users[username] = {'wt_dispname' : wt_dispname,
                            'chat_id' : chat,
                            'log_level' : log_level,
                            'is_superuser' : False}
    storeDatabase()

def newUserChatPair(username, chat_id, langcode=os.getenv('DEFAULT_LANG'), is_private=True, mute='own', wt_dispname = '', log_level = os.getenv('DEFAULT_TELEGRAM_LOGGING_LEVEL'), wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True')):
    users[username] = {'wt_dispname' : wt_dispname,
                            'chat_id' : chat_id,
                            'log_level' : log_level,
                            'is_superuser' : False}
    chats[chat_id] = {'langcode': langcode,
                           'valid' : False,
                           'mute' : mute,
                           'is_private' : is_private,
                           'user' : username,
                           'wt_confirm' : wt_confirm}
    storeDatabase()

def updateUser(user, key, value):
    users[user][key] = value
    storeDatabase()

def updateChat(chat, key, value):
    chats[chat][key] = value
    storeDatabase()

# Run the confiuration, will be executed on first import, only once
# Logging
log = setupLogging()
# Database
chats, users = loadDatabase()

# Multiple Languages:
ml = MulitLanguageMessages()
if not ml.languageSupported(os.getenv('DEFAULT_LANG')):
    log.fatal('[CONFIG] The default language has no associated languagepack. Cannot operate this way.')
    quit()
log.info('[CONFIG] Sytsem Started, Configuration loaded!')