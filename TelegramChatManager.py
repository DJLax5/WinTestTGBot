import BOTConfiguration as cf
import telegram, threading
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import asyncio
import re

class TelegramChatManager:
    ''' This class provides the Chat Management used to handle all messages between Telegram and this software'''

    def __init__(self, messageToWThandler, getOPsHandler, getWinTestDump):
        ''' Construct the chat manager, with an application and the basic push capability '''
        self.bot = telegram.Bot(token=os.getenv('TELEGRAM_TOKEN'))
        self.username = ''
        self._loop = asyncio.new_event_loop()        
        asyncio.set_event_loop(self._loop)
        asyncio.get_event_loop().set_exception_handler(self.handleCoroutineException)
        threading.excepthook = cf.handleUncaughtException
        self.toWT = messageToWThandler
        self.getOPs = getOPsHandler
        self.getWTdump = getWinTestDump
        self._thread = None
        self.defaultLang = os.getenv('DEFAULT_LANG')


        async def getUsername():
            self.username = (await self.bot.get_me()).username
        # Try to get the bot's username and build the app
        try:
            self._loop.run_until_complete(getUsername())            
            self.app = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
        except Exception as e:
            cf.log.fatal('[TCM] Could not establish a connection to Telegram. Is the key correct? Exception: ' + str(e))
            quit()
            
        # Add the command handlers
        self.app.add_handler(CommandHandler('start', self.handleStart, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('verify', self.handleVerify, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('name', self.handleName, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('lang', self.handleLang, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('mute', self.handleMute, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('confirm', self.handleConfirm, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('all', self.handleAll, filters=~filters.UpdateType.EDITED))
        self.app.add_handler(CommandHandler('sudo', self.handleSudo, filters=~filters.UpdateType.EDITED)) # only in private chats
        self.app.add_handler(CommandHandler('leave', self.handleLeave, filters=~filters.UpdateType.EDITED)) 
        self.app.add_handler(CommandHandler('dump', self.handleDump, filters=~filters.UpdateType.EDITED)) # only for super users in private chats
        self.app.add_handler(CommandHandler('makeleave', self.handleMakeLeave, filters=~filters.UpdateType.EDITED)) # only for super users in private chats
        self.app.add_handler(CommandHandler('muteall', self.handleMuteall, filters=~filters.UpdateType.EDITED)) # only for super users in private chats
        self.app.add_handler(CommandHandler('plebs', self.handlePlebs, filters=~filters.UpdateType.EDITED)) # only for super users in private chats
        self.app.add_handler(CommandHandler('loglevel', self.handleLoglevel, filters=~filters.UpdateType.EDITED)) # only for super users in private chats
        self.app.add_handler(CommandHandler('help', self.handleHelp, filters=~filters.UpdateType.EDITED))  
        # And the message handlers      
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE & ~filters.UpdateType.EDITED, self.handleMessage))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUP & ~filters.UpdateType.EDITED & filters.Regex(r'^@'+ self.username + ' '), self.handleGroupMessage))  # Regex to only trigger if the message starts with the bot mention         
        self.app.add_error_handler(self.errorHandler)
        cf.log.info('[TCM] Bot sucessfully instanciated, username: ' + self.username)
        

    def start(self):
        ''' This function will start the polling process of the Telegram bot. '''
        def _start():
            asyncio.set_event_loop(self._loop)
            self.app.run_polling()
        # we'll do the polling in a new thread. this encapsulates it from the rest
        self._thread = threading.Thread(target=_start)
        self._thread.daemon = True
        self._thread.start()
        cf.log.info('[TCM] Telegram application started')
        # Send super-users the boot message
        for user in cf.users:
            if cf.users[user]['is_superuser'] == True:
                chat = cf.users[user]['chat_id']
                self.sendMessage(chat,cf.ml.getMessage(cf.chats[chat]['langcode'], 'BOT_BOOT'))

    def stop(self):
        cf.log.debug('[TCM] Stop event')
        # Send super-users the shutdown event
        for user in cf.users:
            if cf.users[user]['is_superuser'] == True:
                chat = cf.users[user]['chat_id']
                self.sendMessage(chat,cf.ml.getMessage(cf.chats[chat]['langcode'], 'BOT_SHUTDOWN'), wait = True) # we'll need to wait, otherwise the program might exit without sending the message


    def sendMessage(self, chatID, message, wait = False):
        '''Basic function to send a message to a specific chat, this can be called from anywhere at anytime '''
        if chatID == None or chatID == '':
            return
        
        message = telegram.helpers.escape_markdown(message, version=2)
        async def send_message(self, chatID, message):
            try:
                await self.bot.send_message(chat_id=chatID, text=message, parse_mode='MarkdownV2')
            except telegram.error.BadRequest as e:
                cf.log.warning('[TCM] The message could not be sent. Reason: ' + str(e))

        try:
            if not wait:
                asyncio.set_event_loop(self._loop)
                asyncio.ensure_future(send_message(self, chatID, message))
            else:
                future = asyncio.run_coroutine_threadsafe(send_message(self, chatID, message), self._loop)
                future.result() 
        except:
            cf.log.error('[TCM] Could not run the coroutine to send a message.')
   

    async def handleStart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Start the setup conversation after the /start command'''
        
        chat_id = str(update.message.chat_id)
        chat_type = update.message.chat.type

        if cf.chats.get(chat_id): # chat exists in database. /start was unneccesary
            if cf.chats[chat_id]['valid'] == True:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_VALID'),version = 2)
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(cf.chats[chat_id]['langcode'], 'RESTART_UNVALID'),version = 2)
        else: # new chat
            if chat_type == 'private':
                user = update.message.from_user.username
                langcode = update.message.from_user.language_code # try to greet the user in its own language                
                if not cf.ml.languageSupported(langcode):
                    langcode = self.defaultLang
                
                if cf.users.get(user): # we already know the user. Maybe it interacted with the bot in a group?
                    if cf.users[user]['chat_id'] != '': # it should not have a chat set
                        cf.log.warning('[TCM] User '+ user + ' just opend a new chat, while a old chat was existent. Overriding the stored chat.')
                    cf.updateUser(user, 'chat_id', chat_id)
                    cf.newChat(chat_id, langcode=langcode, is_private=True, user=user) # open a new chat, link it to the existing user
                else:
                    cf.newPrivateChat(user, chat_id, langcode)
                cf.log.info('[TCM] A new private chat just started with user ' + user)
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'WELCOME_PRIVATE', vars={'name':update.message.from_user.first_name}),version = 2)
            else:
                langcode = self.defaultLang
                cf.newChat(chat_id, langcode=langcode, is_private=False, groupname = update.message.chat.title, mute='none')
                cf.log.info('[TCM] A new group chat just started: ' + update.message.chat.title)
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'WELCOME_GROUP'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleVerify(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handly /verify command. Try to get the password. '''
        
        chat_id = str(update.message.chat_id)
        chat_type = update.message.chat.type

        if not cf.chats.get(chat_id): 
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        langcode = cf.chats[chat_id]['langcode']
        if await self.sanityCheck(update, silent = True):
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ALREADY_VERIFIED'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        
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
        
    async def handleName(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /name commands. If no key is specified, we'll try to set the telegram username as the name. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
            
        langcode = cf.chats[chat_id]['langcode']
        charlim = int(os.getenv('WT_STN_LIMIT')) - len(os.getenv('WT_CALL_PREFIX')) - len(os.getenv('WT_CALL_SUFFIX'))
        if context.args == []: # if no name is specified, we'll try to use the TG username
            if len(user) <= charlim:
                cf.updateUser(user, 'wt_dispname', user.upper())
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NAME_SET_USERNAME', vars={'uname':user.upper()}),version = 2)
                cf.log.info('[TCM] User ' + user + ' updated its Win-Test display name to ' + user.upper())
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NAME_SYNTAX_UNAME', vars={'uname':user.upper(),'charlim':charlim}),version = 2)
                
        else:
            dispname = " ".join(context.args)
            if len(dispname) <= charlim:
                cf.updateUser(user, 'wt_dispname', dispname.upper())
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NAME_SET_SUCCESS', vars={'dispname':dispname.upper()}),version = 2)  
                cf.log.info('[TCM] User ' + user + ' updated its Win-Test display name to ' + dispname.upper())             
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NAME_SET_FAILED', vars={'charlim':charlim}),version = 2)
        
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleLang(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /lang commands. This switches the language of the current chat. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if context.args == []:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LANG_SYNTAX', vars={'languages':cf.ml.getLanguagesString()}),version = 2)
        else:
            newLangcode = " ".join(context.args).lower()
            if cf.ml.languageSupported(newLangcode):
                cf.updateChat(chat_id, 'langcode', newLangcode)
                cf.log.info('[TCM] User ' + user + ' just updated the lanuage for a chat to ' + newLangcode)
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(newLangcode, 'LANG_SUCCESS'),version = 2)
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LANG_NOT_FOUND', vars={'languages':cf.ml.getLanguagesString()}),version = 2)
            
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleMute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /mute commands. This mutes Win-Test Messages into this chat. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']

        if context.args == []:
            if chat_type == 'private':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_SYNTAX_PRV'),version = 2)
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_SYNTAX_GRP'),version = 2)
        else:
            mute = " ".join(context.args).lower()
            if mute == 'all':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_ALL'),version = 2)
                cf.updateChat(chat_id, 'mute', 'all')
                cf.log.info('[TCM] User ' + user + ' muted a chat.')
            elif mute == 'own':
                if chat_type == 'private':
                    message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_OWN_PRV'),version = 2)
                    cf.updateChat(chat_id, 'mute', 'own')
                    cf.log.info('[TCM] User ' + user + ' muted his own messages.')
                else:
                    message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_OWN_GRP'),version = 2)
            elif mute == 'none':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_NONE'),version = 2)
                cf.updateChat(chat_id, 'mute', 'none')
                cf.log.info('[TCM] User ' + user + ' unmuted a chat.')
            else:
                if chat_type == 'private':
                    message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_SYNTAX_PRV'),version = 2)
                else:
                    message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_SYNTAX_GRP'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleConfirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /confirm commands. This enables/disables the confirmation messages weather the Message arrived to Win-Test. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if context.args == []:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'CONFIRM_SYNTAX'),version = 2)
        else:
            newState = " ".join(context.args).lower()
            if newState == 'on':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'CONFIRM_ON'),version = 2)
                cf.updateChat(chat_id, 'wt_confirm', True)
                cf.log.info('[TCM] User ' + user + ' enabled Win-Test confirmation messages.')
            elif newState == 'off':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'CONFIRM_OFF'),version = 2)
                cf.updateChat(chat_id, 'wt_confirm', False)
                cf.log.info('[TCM] User ' + user + ' disabled Win-Test confirmation messages.')
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'CONFIRM_SYNTAX'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleAll(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /all command. This enables/disables the Telegram to Telegram notifications. (Cross chat notifications) '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if context.args == []:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ALL_SYNTAX'),version = 2)
        else:
            newState = " ".join(context.args).lower()
            if newState == 'on':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ALL_ON'),version = 2)
                cf.updateChat(chat_id, 'tg_to_tg', True)
                cf.log.info('[TCM] User ' + user + ' enabled TG to TG messages.')
            elif newState == 'off':
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ALL_OFF'),version = 2)
                cf.updateChat(chat_id, 'tg_to_tg', False)
                cf.log.info('[TCM] User ' + user + ' disabled TG to TG messages.')
            else:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ALL_SYNTAX'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleSudo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /sudo commands. This makes the current user a Super-User. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            
        langcode = cf.chats[chat_id]['langcode']

        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'SUDO_GROUP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == True:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'SUDO_ALREADY'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        
        if context.args == []: # check syntax
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'SUDO_SYNTAX'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        key = " ".join(context.args)
        if key == os.getenv('SUPER_USER_KEY'):
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'SUDO_SUCCESS'),version = 2)
            cf.updateUser(user, 'is_superuser', True)
            cf.log.info('[TCM] User ' + user + ' is now a superuser.')
        else:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'SUDO_FAILED'),version = 2)
            cf.log.warning('[TCM] Superuser verification failed by user ' + user + ', tried key: ' + key)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleLeave(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /leave commands. This deletes all stored data, without asking!'''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        
        langcode = cf.chats[chat_id]['langcode']
        cf.remove(chat_id)      
        if chat_type == 'private':
             cf.log.info('[TCM] User '+ user + ' deletet itself.')
        else:
            cf.log.info('[TCM] User '+ user + ' just removed the group ' +update.message.chat.title)
        message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LEAVE_SUCCESS'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')
    
    async def handleDump(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /dump commands. This displays all stored data to super users. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == False:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        dump_msg =  telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_PREFIX'),version = 2) + '\n\n'
        
        for user in cf.users:
            if cf.users[user]['chat_id'] != '':
                data_dump =  dict(cf.users[user], **cf.chats[cf.users[user]['chat_id']])
                data_dump.pop('groupname') # remove the not printed keys, otherwise a warning would arise
                data_dump.pop('chat_id')
                data_dump.pop('is_private')
                dump_msg += telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_USER_PRV', vars=data_dump),version = 2) + '\n'
            else:
                data_dump = dict({'user':user}, **cf.users[user])
                dump_msg += telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_USER', vars=data_dump),version = 2) + '\n'
        
        anyGroup = False
        
        for chat in cf.chats:
            if cf.chats[chat]['is_private'] == False: # remove the not printed keys, otherwise a warning would arise
                if anyGroup == False:
                    dump_msg += '\n' + telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_MIDFIX'),version = 2) + '\n\n'
                    anyGroup = True
                data_dump = dict(cf.chats[chat])
                data_dump.pop('is_private')
                data_dump.pop('user')
                dump_msg += telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_GRPchat', vars=data_dump),version = 2) + '\n'
        data_dump = self.getWTdump()
        dump_msg += '\n' + telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'DUMP_SUFFIX', vars=data_dump),version = 2)
        await update.message.reply_text(dump_msg, parse_mode='MarkdownV2')


    async def handleMakeLeave(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /makeleave commands. This allows super users to remove users. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == False:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return

        if context.args == []: # check syntax
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MAKELEAVE_SYNTAX'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        name = " ".join(context.args)
        if cf.users.get(name) != None:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MAKELEAVE_USER_SUCCESS', vars={'user':name}),version = 2)
            cf.removeUser(name)
            cf.log.info('[TCM] Super-user ' + user + ' just removed ' + name)
        else:
            found = False
            for chat in cf.chats:
                if cf.chats[chat]['groupname'] == name:
                    message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MAKELEAVE_GRP_SUCCESS', vars={'groupname':name}),version = 2)
                    cf.remove(chat)
                    cf.log.info('[TCM] Super-user ' + user + ' just removed ' + name)
                    found = True
                    break         
            if not found:
                message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MAKELEAVE_NOT_FOUND'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleMuteall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /muteall commands. This allows super users to mute all chats after a contest. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == False:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return

        for chat in cf.chats:
            if chat == chat_id:
                continue
            cf.updateChat(chat, 'mute', 'all')
            us_langcode = cf.chats[chat]['langcode']
            self.sendMessage(chat, cf.ml.getMessage(us_langcode, 'MUTE_ALL_PRV' if cf.chats[chat]['is_private'] == True else 'MUTE_ALL_GRP'))
            
        message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'MUTE_ALL_SUCCESS'),version = 2)
        cf.log.info('[TCM] Super-User ' + user + ' just muted all chats.')
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handlePlebs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /plebs commands. This removes the super-user status from a user. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == False:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return

        cf.updateUser(user, 'is_superuser', False)
        cf.updateUserLogging(user, 'none')
        cf.log.info('[TCM] Super-User ' + user + ' gave up on its super-user rights')
        message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'TO_PLEBS'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    async def handleLoglevel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /loglevel commands. This allows super-users to set a loglevel '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        if chat_type != 'private':
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_GRP'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        if cf.users[user]['is_superuser'] == False:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'ONLY_SUPERUSER_PRV'),version = 2) 
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        
        if context.args == []: # check syntax
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LOGLEVEL_SYNTAX'),version = 2)
            await update.message.reply_text(message, parse_mode='MarkdownV2')
            return
        loglevel = " ".join(context.args)
        if cf.updateUserLogging(user, loglevel) == 0:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LOGLEVEL_SUCCESS'),version = 2)
        else:
            message = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'LOGLEVEL_SYNTAX'),version = 2)
        await update.message.reply_text(message, parse_mode='MarkdownV2')

        

    async def handleHelp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' Handle /help commands. This displays all commands and the current settings. '''
        chat_type = update.message.chat.type
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username
        if chat_type == 'private':
            if not await self.sanityCheck(update):
                return
        else:
            if not await self.sanityCheckGroup(update):
                return
            if cf.users.get(user) == None:
                cf.newUser(user)
                cf.log.info('[TCM] New user interacted with this bot: ' + user)
        langcode = cf.chats[chat_id]['langcode']
        settings = {'wt_dispname' : cf.users[user]['wt_dispname'],
                    'languages' : cf.ml.getLanguagesString(),
                    'mute' : cf.chats[chat_id]['mute'],
                    'wt_confirm' : 'on' if cf.chats[chat_id]['wt_confirm'] == True else 'off',
                    'tg_to_tg' : 'on' if cf.chats[chat_id]['tg_to_tg'] == True else 'off'}
        if chat_type != 'private':
            settings['botuname'] = self.username
            message =  telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'HELP_GRP', vars=settings),version = 2) + '\n\n'
        else:
            if cf.users[user]['is_superuser'] == True:
                settings['log_level'] = cf.users[user]['log_level']
                message =  telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'HELP_SUSER', vars=settings),version = 2) + '\n\n'
            else:
                message =  telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'HELP_PRV', vars=settings),version = 2) + '\n\n'
        await update.message.reply_text(message, parse_mode='MarkdownV2')

        
    async def handleMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        '''Handle the incoming messages and send them to WT'''
        chat_id = str(update.message.chat_id)
        user = update.message.from_user
        first_name = user.first_name
        username = user.username
        langcode = user.language_code
        text = update.message.text
       
        if await self.sanityCheck(update):
            confirm = cf.chats[chat_id]['wt_confirm']
            langcode = cf.chats[chat_id]['langcode']
            if cf.users[username]['wt_dispname'] != '':
                dispname = os.getenv('WT_CALL_PREFIX') + cf.users[username]['wt_dispname'] + os.getenv('WT_CALL_SUFFIX')
                msg = ''
            else:
                dispname =  cf.ml.getMessage(self.defaultLang, 'BOT_STATION')
                msg = cf.ml.getMessage(langcode, 'REQUEST_WTNAME', vars={'name':first_name})
            resp = self._forwardToWT(dispname, text, langcode)

            if resp == '':
                if confirm:
                    resp = cf.ml.getMessage(langcode, 'WT_CONFIRM')
                ops = self.getOPs()
                for chat in cf.chats:
                    if chat == chat_id:
                        continue
                    if cf.chats[chat]['tg_to_tg'] == True and cf.chats[chat]['mute'] != 'all':
                        if cf.chats[chat]['is_private'] == False:
                            self.sendMessage(chat, dispname + ':\n' + text)
                        elif not (cf.chats[chat]['mute'] == 'own' and cf.users[cf.chats[chat]['user']]['wt_dispname'] in ops):
                            self.sendMessage(chat, dispname + ':\n' + text)

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
            resp = self._forwardToWT(dispname, text, langcode)

            if resp == '':
                if confirm:
                    resp = cf.ml.getMessage(langcode, 'WT_CONFIRM')
                ops = self.getOPs()
                for chat in cf.chats:
                    if chat == chat_id:
                        continue
                    if cf.chats[chat]['tg_to_tg'] == True and cf.chats[chat]['mute'] != 'all':
                        if cf.chats[chat]['is_private'] == False:
                            self.sendMessage(chat, dispname + ':\n' + text)
                        elif not (cf.chats[chat]['mute'] == 'own' and cf.users[cf.chats[chat]['user']]['wt_dispname'] in ops):
                            self.sendMessage(chat, dispname + ':\n' + text)

            if msg != '' and resp != '':
                msg += '\n\n ---- \n\n' + resp
            else:
                msg += resp

            if msg != '':
                msg = telegram.helpers.escape_markdown(msg, version = 2)
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
    
    async def errorHandler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        ''' If a uncaught telegram  error within a telegram message arises. '''
        cf.log.error('[TCM] An uncaught exception in the telegram module occurred. This bot will continue to run. \nException: ' + str(context.error), exc_info=context.error)

    def handleCoroutineException(self, coro, context):
        cf.log.error('[TCM] A coroutine failed to execute! \nException: ' + str(context['exception']), exc_info=context['exception'])
            
    async def sanityCheck(self, update, silent = False):
        ''' Sanity check to limit access only to existing well-behaved users. This check is for private chats.'''
        chat_id = str(update.message.chat_id)
        user = update.message.from_user.username

        if not cf.chats.get(chat_id):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'), version = 2)
            if not silent:
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
                cf.log.warning('[TCM] Sanity check failed. Unknown chat.')
            return False
        langcode = cf.chats[chat_id]['langcode']
        if not cf.users.get(user):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'UNKNOWN_CHAT_ERROR'), version = 2)
            if not silent:
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
                cf.log.warning('[TCM] Sanity check failed. Unknown user.')
            return False
        if cf.chats[chat_id]['valid'] == False:
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR'), version = 2)
            if not silent:
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
                cf.log.warning('[TCM] Sanity check failed. User not verified.')
            return False
        if cf.chats[chat_id]['user'] != user:
            cf.log.warning('[TCM] Database inconsistency. Chat points to wrong user. Fixing that.')
            cf.updateChat(chat_id, 'user', user)
        if cf.users[user]['chat_id'] != chat_id:
            cf.log.warning('[TCM] Database inconsistency. User points to wrong chat. Fixing that.')
            cf.updateUser(user, 'chat_id', chat_id)

        return True

    async def sanityCheckGroup(self, update, silent = False):
        ''' Sanity check to limit access only to existing well-behaved users. '''
        chat_id = str(update.message.chat_id)
        if not cf.chats.get(chat_id):
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(self.defaultLang, 'UNKNOWN_CHAT_ERROR'), version = 2)
            if not silent:
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
                cf.log.warning('[TCM] Sanity check failed. Unknown chat.')
            return False
        langcode = cf.chats[chat_id]['langcode']
        if cf.chats[chat_id]['valid'] == False:
            msg = telegram.helpers.escape_markdown(cf.ml.getMessage(langcode, 'NOT_VALID_ERROR'), version = 2)
            if not silent:
                await update.message.reply_text(msg, parse_mode='MarkdownV2')
                cf.log.warning('[TCM] Sanity check failed. User not verified.')
            return False
        return True

    def _forwardToWT(self, dispname, message, langcode):
        status = self.toWT(dispname, message)
        if status == 0:
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

        