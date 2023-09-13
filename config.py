import os
from dotenv import load_dotenv
import logging
import json

def setupLogging():
    # Set up the logger with file and console handlers
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    # Create a console handler and set its level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(os.getenv('CONSOLE_LOGGING_LEVEL'))
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    # Create a file handler and set its level 
    file_handler = logging.FileHandler(os.getenv('LOG_FILE_PATH'), mode='a')
    file_handler.setLevel(os.getenv('FILE_LOGGING_LEVEL'))
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='[%d.%m.%y %H:%M:%S]'))

    # Add the handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


# Run the confiuration, will be executed on first import, only once
load_dotenv() # load the .env keys
log = setupLogging()
log.info('[CONFIG] Sytsem Started, Configuration loaded!')