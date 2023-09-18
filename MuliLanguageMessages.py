import sys, os, json

class MulitLanguageMessages:
    ''' This class provides easy handlers to acess the multi language messages. The languagefiles are stored in /lang/ in the json format'''

    langDir = os.getenv('LANGUAGEPACK_PATH')


    def __init__(self, log):
        ''' Constructor which will load all present files and messages '''

        self.MESSAGES = {} # Stores all messages of all languages
        self.log = log
        for filename in os.listdir(MulitLanguageMessages.langDir): # just read every json file in the lang file
            if filename.endswith('.json'):
                langcode = filename.split('.')[0] # NOTE: This forbids language codes to contain a dot.
                langcode = langcode.lower() # DEFINE: Langcodes are lowercase
                with open(os.path.join(MulitLanguageMessages.langDir, filename), 'r', encoding='utf-8') as f:
                    messages = json.loads(f.read())
                    self.MESSAGES[langcode] = messages
                    
                self.log.info('[ML] Languagepack read: ' + langcode)

    def getMessage(self, langcode, msg_id, vars = None):
        ''' This function finds and builds the requested message of the requestes language. Via the vars dict you can replace an arbitrary amount of parameters in the messages. '''

        # sanity checks
        if not self.MESSAGES.get(langcode):
            self.log.error('[ML] The requested languagecode is not available: ' + langcode)
            return '[ERROR] The requested languagecode is not available: ' + langcode
        
        if not self.MESSAGES[langcode].get(msg_id):
            self.log.error('[ML] The requested Message-ID ('+ msg_id + ') is not present in the languagepack!')
            return '[ERROR] The requested Message-ID ('+ msg_id + ') is not present in the languagepack!'

        # extract message
        message = self.MESSAGES[langcode][msg_id]
        
        # replace parameters
        if vars:
            for key, value in vars.items():
                if f"[{key}]" not in message:
                    self.log.warning('[ML] The variable ' + key + ' is not present in the message-id ' + msg_id + ' of languagepack ' + langcode)
                else:
                    message = message.replace(f"[{key}]", str(value))
        
        return message

    def languageSupported(self, langcode):
        ''' Simple check weather a language code exists'''
        return self.MESSAGES.get(langcode) != None
    
    def getLanguagesString(self):
        ''' Restruns a string with all supported langages'''
        msg = ''
        for lang in self.MESSAGES:
            msg += lang + ': ' + self.MESSAGES[lang]['LANGUAGE'] + '\n'
        return msg