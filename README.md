# Win-Test Telegram Bot

This bot will be your bridge between the Win-Test Chat and Telegram. The bot can be part of a group chat or multiple private chats. 
It brings all OPs of a multi-op station closer in a contest.

At any doubt in operation use the Telegram command `/help`.

Feel free to contribute!

The messages the bot can send are stored in the `lang` folder. There you would fix a typo or add a new language. Please use the ISO language code as filename. All JSON files in this folder are automatically loaded at startup. Adding a language is as simple as adding a new language file.
There are running installments of this bot which regularly pull the main branch. Please push new features into `dev`. 

To gracefully stop the bot please always use `Ctrl+C`. Killing the bot may leave open sockets.

## Features
- Sends messages directly to a Win-Test multi-op station, it will appear in the usual Win-Test Chat.
- Can receive Win-Test messages and publish them to Telegram. 
- This bot works in groups aswell as private chats. Private chats offer more settings.
- `/mute` You can mute a chat if you're not particpating in a current contest. The bot keeps track of all Win-Test stations and OPON commands. You can also mute your private chat automatically, if you're currently operating.
- You can have super-users which have full control over the bot and its users via Telegram.
- `/name` You can save a different name for each Telegram user. This name will appear in Win-Test as the station form which the messages appear to come from. You can define prefixes and suffixes for this name.
- `/lang` Multi language support. The bot can communicate with different users in different languages. This language is unique per chat the bot is used in.
- Customizable per chat. A few more comfort features about when and about what you will receive a Telegram message from this bot.
- Intensive logging. A log file is created and basically all actions are logged. This is great for debugging and identifying issues.
- Protected. As Telegram bots are public, new users need to authenticate themselfs before they can send/receive messages from your Win-Test stations.

### Improvements
Some possible future improvements:
- Currently only the OPON / OPOFF commands are registered to detect the current OP. There are more Win-Test messages we could evaluate.
- Currently only messages to all stations are read/sent. Message to a single station could be implemented.

## How-To Setup
You can easily run your own instance of this bot. 
You'll need:
- A pc within the same network as the Win-Test 
- A python environment with the packages of `requirements.txt` installed (Tested in Python 3.11.). You can directly create this environment with `conda` using `conda env create --prefix ./env --file environment.yml`
- A Telegram bot token. Create one within Telegram with `@BotFather`. Disable privacy mode for this bot to be able to use group chats.

To run the bot:
1. Clone this repo
1. Copy the file `.demoenv` to `.env`
1. Edit the `.env` file. Set your Win-Test broadcast IP, Port & Subnet, Telegram token and the passwords for users and super-users.
1. Run the bot (`WinTestTGBot.py`) in your python environment. If you're on a windows machine and used the environment.yml file to setup your environment, you can run the `start.bat` file. Make sure you allow python through your firewall.
1. Start the Telegram bot by sending `/start` to it. 

Have fun!
## Disclaimer
This is a hobby project. There is no warranty whatsoever. Use at your own risk.

Respect the license. 
Do anything, but make sure you reference me as your source.
You may not comercialize this bot or anything that is bulid on-top of it.

## Known Bugs
- If the system running this bot loses the internet connection, this bot will hang. A manual restart may be required.
- If a user changes its username, the bot will no longer recognise the user
- Works only with a limited number of users (about 10) 
