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

def checkDatabase(chats, users, modified = False):
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
            chats[chat]['wt_confirmed'] = True
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing wt_confirmed tag. Restoring to default.')
            return checkDatabase(chats, users, modified)
            
        if chats[chat].get('tg_to_tg') == None:
            chats[chat]['tg_to_tg'] = True
            modified = True
            log.warning('[CONFIG] Database integretry compromised, missing tg_to_tg tag. Restoring to default.')
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


def newChat(chat_id, langcode=os.getenv('DEFAULT_LANG'), is_private=True, mute='none', user='', wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True'), tgTOtg=True):
    if user != '' and not users.get(user):
        log.warn('[CONFIG] Trying to create a new chat referencing a non-existing user. This is invalid, resetting user reference. ')
        user = ''
    chats[chat_id] = {'langcode': langcode,
                           'valid' : False,
                           'mute' : mute,
                           'is_private' : is_private,
                           'user' : user,
                           'wt_confirm' : wt_confirm,
                           'tg_to_tg' : tgTOtg}
    storeDatabase()

def newUser(username, wt_dispname = '', chat = '', log_level = 'none'):
    if chat != '' and not chats.get(chat):
        log.warn('[CONFIG] Trying to create a new user referencing a non-existing chat. This is invalid, resetting chat reference. ')
        chat = ''
    users[username] = {'wt_dispname' : wt_dispname,
                            'chat_id' : chat,
                            'log_level' : log_level,
                            'is_superuser' : False}
    storeDatabase()

def newPrivateChat(username, chat_id, langcode=os.getenv('DEFAULT_LANG'), mute='own', wt_dispname = '', log_level = 'none', wt_confirm = (os.getenv('TG_CONFIRM_DEFAULT') == 'True'), tgTOtg=True):
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
                           'tg_to_tg' : tgTOtg}
    storeDatabase()

def updateUser(user, key, value):
    if users.get(user) == None:
        log.error('[TCM] Unable to find user ' + user)
        return
    users[user][key] = value
    storeDatabase()

def updateChat(chat, key, value):
    if chats.get(chat) == None:
        log.error('[TCM] Unable to find chat ' + chat)
        return
    chats[chat][key] = value
    storeDatabase()

# Run the confiuration, will be executed on first import, only once
# Logging
log = setupLogging()
# Database
chats, users = loadDatabase()
chats, users, modified = checkDatabase(chats, users)
if modified:
    storeDatabase()

del modified
# Multiple Languages:
ml = MulitLanguageMessages(log)
if not ml.languageSupported(os.getenv('DEFAULT_LANG')):
    log.fatal('[CONFIG] The default language has no associated languagepack. Cannot operate this way.')
    quit()
log.info('[CONFIG] Sytsem Started, Configuration loaded!')