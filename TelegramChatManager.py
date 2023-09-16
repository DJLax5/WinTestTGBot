import config as cf
import telegram, threading
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import asyncio
import re

class TelegramChatManager:
    ''' This class provides the Chat Management used to handle all messages between Telegram and this software'''

    def __init__(self, messageToWThandler):
        ''' Construct the chat manager, with an application and the basic push capability '''
        self.bot = telegram.Bot(token=os.getenv('TELEGRAM_TOKEN'))
        self.username = ''
        self._loop = asyncio.new_event_loop()        
        asyncio.set_event_loop(self._loop)
        
        async def getUsername():
            self.username = (await self.bot.get_me()).username
        
        self._loop.run_until_complete(getUsername())
        
        self.app = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
        self.app.add_handler(CommandHandler('start', self.handleStart))
        self.app.add_handler(CommandHandler('verify', self.handleVerify))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, self.handleMessage))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUP & filters.Regex(r'^@'+ self.username + ' '), self.handleGroupMessage))        
        
        self.toWT = messageToWThandler
        self._thread = None

        self.defaultLang = os.getenv('DEFAULT_LANG')
        
        cf.log.info('[TCM] Bot sucessfully instanciated, username: ' + self.username)

    def start(self):
        ''' This function will start the polling process of the Telegram bot. '''
        def _start():
            asyncio.set_event_loop(self._loop)
            self.app.run_polling()
        self._thread = threading.Thread(target=_start)
        self._thread.daemon = True
        self._thread.start()
        cf.log.info('[TCM] Telegram application started')

    def stop(self):
        cf.log.debug('[TCM] Stop event')
        # NOTE: This funtion does not do anything as the application thread is set as daemon. This function is reserved as some cleanup may be done here

    def sendMessage(self, chatID, message):
        '''Basic function to send a message to a specific chat, this can be called from anywhere at anytime '''
        if chatID == None or chatID == '':
            return
        message = telegram.helpers.escape_markdown(message, version=2)
        async def send_message(self, chatID, message):
            try:
                await self.bot.send_message(chat_id=chatID, text=message, parse_mode='MarkdownV2')
            except telegram.error.BadRequest as e:
                cf.log.warning('[TCM] The message could not be sent. Reason: ' + str(e))

        asyncio.set_event_loop(self._loop)
        asyncio.ensure_future(send_message(self, chatID, message))

    async def handleStart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Start the setup conversation after the /start command'''
        
        chat_id = str(update.message.chat_id)
        chat_type = update.message.chat.type

        if cf.chats.get(chat_id):
            if cf.chats[chat_id]['valid'] == True:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_VALID'),version = 2)
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_UNVALID'),version = 2)
                
        else:
            if chat_type == 'private':
                langcode = update.message.from_user.language_code
                user = update.message.from_user.username
                if not cf.ml.languageSupported(langcode):
                    langcode = self.defaultLang
                
                if cf.users.get(user):
                    if cf.users[user]['chat_id'] != '':
                        cf.log.warning('[TCM] User '+ user + ' just opend a new chat, while a old chat was existent. Overriding the stored chat.')
                    cf.users[user]['chat_id'] = chat_id # the cange in the database will be stored to disk in the newChat command
                    cf.newChat(chat_id, langcode=langcode, is_private=True, user=user)
                else:
                    cf.newUserChatPair(user, chat_id, langcode, is_private=True)
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'WELCOME_PRIVATE', vars={'name':update.message.from_user.first_name}),version = 2)
            else:
                langcode = self.defaultLang
                cf.newChat(chat_id, langcode=langcode, is_private=False)
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'WELCOME_GROUP'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleVerify(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Start the setup conversation after the /start command'''
        
        chat_id = str(update.message.chat_id)
        chat_type = update.message.chat.type

        if not cf.chats.get(chat_id):
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        langcode = cf.chats[chat_id]['langcode']
        if context.args == []: # check syntax
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'INVALID_VERIFY_SYNTAX'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        key = " ".join(context.args)
        if key == os.getenv('MAGIC_KEY'):
            if chat_type == 'private':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'VERIFY_SUCCESS_PRIVATE'),version = 2)
            else: 
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'VERIFY_SUCCESS_GROUP', vars={'botuname': self.username}),version = 2)
            cf.updateChat(chat_id, 'valid', True)
            cf.log.info('[TCM] New chat verified.')
        else:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'VERIFY_FAILED'),version = 2)
            cf.log.warning('[TCM] Chat verification failed, tried key: ' + key)
        await update.message.reply_text(message, parse_mode='MarkdownV2')
        

    async def handleMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Handle the incoming messages and send them to WT'''
        chat_id = str(update.message.chat_id)
        user = update.message.from_user
        first_name = user.first_name
        last_name = user.last_name
        username = user.username
        langcode = user.language_code
        text = update.message.text
        cf.log.debug('[TCM] Private message: {} from chat_id : {}  firstname : {} lastname : {}  username: {} langcode: {}'. format(text, chat_id, first_name, last_name , username, langcode))

        if await self.sanityCheck(update):
            confirm = cf.chats[chat_id]['wt_confirm']
            langcode = cf.chats[chat_id]['langcode']
            if cf.users[username]['wt_dispname'] != '':
                dispname = os.getenv('WT_CALL_PREFIX') + cf.users[username]['wt_dispname'] + os.getenv('WT_CALL_SUFFIX')
                msg = ''
            else:
                dispname =  cf.ml.getMessage(self.defaultLang, 'BOT_STATION')
                msg = cf.ml.getMessage(langcode, 'REQUEST_WTNAME', vars={'name':first_name})
            resp = self._forwardToWT(dispname, text, confirm, langcode)
            if msg != '' and resp != '':
                msg += '\n\n ---- \n\n' + resp
            else:
                msg += resp

            if msg != '':
                msg = telegram.helpers.escape_markdown(msg, version = 2)
                await update.message.reply_text(msg, parse_mode='MarkdownV2')


    async def handleGroupMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Handle the incoming messages and send them to WT'''
        chat_id = str(update.message.chat_id)
        user = update.message.from_user
        first_name = user.first_name
        last_name = user.last_name
        username = user.username
        langcode = user.language_code
        text = re.sub(r'^@'+ self.username + ' ', '', update.message.text)
        cf.log.debug('[TCM] Group message: {} from chat_id : {}  firstname : {} lastname : {}  username: {} langcode: {}'. format(text, chat_id, first_name, last_name , username, langcode))
        
        if await self.sanityCheckGroup(update):
            confirm = cf.chats[chat_id]['wt_confirm']
            langcode = cf.chats[chat_id]['langcode']
            if cf.users.get(username) and cf.users[username]['wt_dispname'] != '':
                dispname = os.getenv('WT_CALL_PREFIX') + cf.users[username]['wt_dispname'] + os.getenv('WT_CALL_SUFFIX')
                msg = ''
            else:
                dispname = cf.ml.getMessage(self.defaultLang, 'BOT_STATION')
                msg = cf.ml.getMessage(langcode, 'REQUEST_WTNAME', vars={'name':first_name})
            resp = self._forwardToWT(dispname, text, confirm, langcode)
            if msg != '' and resp != '':
                msg += '\n\n ---- \n\n' + resp
            else:
                msg += resp

            if msg != '':
                msg = telegram.helpers.escape_markdown(msg, version = 2)
                await update.message.reply_text(msg, parse_mode='MarkdownV2')

            
    async def sanityCheck(self, update):
        ''' Sanity check to limit access only to existing well-behaved users. '''
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username

        if not cf.chats.get(chat_id):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'), version = 2)
            await update.message.reply_text(msg, parse_mode='MarkdownV2')
            cf.log.warning('[TCM] Sanity check failed. Unknown chat.')
            return False
        langcode = cf.chats[chat_id]['langcode']
        if not cf.users.get(user):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'UNKNOWN_CHAT_ERROR'), version = 2)
            await update.message.reply_text(msg, parse_mode='MarkdownV2')
            cf.log.warning('[TCM] Sanity check failed. Unknown user.')
            return False
        if cf.chats[chat_id]['valid'] == False:
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR'), version = 2)
            await update.message.reply_text(msg, parse_mode='MarkdownV2')
            cf.log.warning('[TCM] Sanity check failed. User not verified.')
            return False
        return True

    async def sanityCheckGroup(self, update):
        ''' Sanity check to limit access only to existing well-behaved users. '''
        chat_id = str(update.message.chat_id)
        if not cf.chats.get(chat_id):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'), version = 2)
            await update.message.reply_text(msg, parse_mode='MarkdownV2')
            return False
        langcode = cf.chats[chat_id]['langcode']
        if cf.chats[chat_id]['valid'] == False:
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR'), version = 2)
            await update.message.reply_text(msg, parse_mode='MarkdownV2')
            return False
        return True

    def _forwardToWT(self, dispname, message, confirm, langcode):
        status = self.toWT(dispname, message)
        if status == 0:
            if confirm == True:
                return cf.ml.getMessage(langcode, 'WT_CONFIRM')
            else:
                return ''
        elif status == 1:
            return cf.ml.getMessage(langcode, 'WT_ENCODING_ERROR')
        elif status == 2:
            return cf.ml.getMessage(langcode, 'WT_MSG_LONG_ERROR', vars={'charlimit':os.getenv('WT_MSG_LIMIT')})
        elif status == 3:
            charlimit = int(os.getenv('WT_STN_LIMIT')) - int(os.get('WT_CALL_PREFIX')) - int(os.get('WT_CALL_SUFFIX'))
            return cf.ml.getMessage(langcode, 'WT_STN_LONG_ERROR', vars={'stnname': dispname, 'charlimit' : str(charlimit)})
        else:
            cf.log.error('[TCM] Unknown response code from BOT!')
            return cf.ml.getMessage(langcode, 'UNKNOWN_ERROR')

        