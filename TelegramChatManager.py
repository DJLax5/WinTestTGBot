import config as cf
import telegram
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
        self.app = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
        self.app.add_handler(CommandHandler("start", self.handleStart))

        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handleMessage))
        
        self.toWT = messageToWThandler
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.defaultLang = os.getenv('DEFAULT_LANG')

    def start(self):
        ''' This function will start the polling process of the Telegram bot. '''
        self.app.run_polling()

    def stop(self):
        self.app.stop()

    def sendMessage(self, chatID, message):
        '''Basic function to send a message to a specific chat, this can be called from anywhere at anytime '''
        if chatID == None or chatID == '':
            return
        message = telegram.helpers.escape_markdown(message, version=2)
        async def send_message(self, chatID, message):
            try:
                await self.bot.send_message(chat_id=chatID, text=message, parse_mode='MarkdownV2')
            except telegram.error.BadRequest as e:
                cf.log.warn('[TCM] The message could not be sent. Reason: ' + str(e))

        asyncio.set_event_loop(self._loop)
        asyncio.ensure_future(send_message(self, chatID, message))

    async def handleStart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start the setup conversation after the /start command"""
        chatid = str(update.message.chat_id)
        print(chatid)
        await update.message.reply_text('Hello World\!', parse_mode='MarkdownV2')

    async def handleMessage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start the setup conversation after the /start command"""
        chatid = str(update.message.chat_id)
        text = update.message.text
        self.toWT('DM7HB', text)
        print(chatid)
        await update.message.reply_text('Hello World\!', parse_mode='MarkdownV2')