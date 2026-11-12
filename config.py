import os
import subprocess
from dotenv import load_dotenv
load_dotenv()

from utils.i18n import strings
from datetime import datetime

# We expose variables for access from other modules

from aient.aient.utils import prompt
from aient.aient.core.utils import update_initial_model, BaseAPI
from aient.aient.models import chatgpt, PLUGINS, whisper

from telegram import InlineKeyboardButton

NICK = os.environ.get('NICK', None)
PORT = int(os.environ.get('PORT', '8080'))
BOT_TOKEN = os.environ.get('BOT_TOKEN', None)
RESET_TIME = int(os.environ.get('RESET_TIME', '3600'))
if RESET_TIME < 60:
    RESET_TIME = 60

BASE_URL = os.environ.get('BASE_URL', 'https://api.groq.com/openai/v1/chat/completions')
API_KEY = os.environ.get('API_KEY', None)
MODEL = os.environ.get('MODEL', 'llama-3.3-70b-versatile')

WEB_HOOK = os.environ.get('WEB_HOOK', None)
CHAT_MODE = os.environ.get('CHAT_MODE', "global")
GET_MODELS = (os.environ.get('GET_MODELS', "True") == "False") == False

PASS_HISTORY = os.environ.get('PASS_HISTORY', 9999)
if type(PASS_HISTORY) == str:
    if PASS_HISTORY.isdigit():
        PASS_HISTORY = int(PASS_HISTORY)
    elif PASS_HISTORY.lower() == "true":
        PASS_HISTORY = 9999
    elif PASS_HISTORY.lower() == "false":
        PASS_HISTORY = 0
    else:
        PASS_HISTORY = 9999
else:
    PASS_HISTORY = 9999

PREFERENCES = {
    "PASS_HISTORY"      : int(PASS_HISTORY),
    "IMAGEQA"           : (os.environ.get('IMAGEQA', "False") == "True") == False,
    "LONG_TEXT"         : (os.environ.get('LONG_TEXT', "True") == "False") == False,
    "LONG_TEXT_SPLIT"   : (os.environ.get('LONG_TEXT_SPLIT', "True") == "False") == False,
    "FILE_UPLOAD_MESS"  : (os.environ.get('FILE_UPLOAD_MESS', "True") == "False") == False,
    "FOLLOW_UP"         : (os.environ.get('FOLLOW_UP', "False") == "False") == False,
    "TITLE"             : (os.environ.get('TITLE', "False") == "False") == False,
    # "TYPING"            : (os.environ.get('TYPING', "False") == "False") == False,
    "REPLY"             : (os.environ.get('REPLY', "False") == "False") == False,
}

LANGUAGE = os.environ.get('LANGUAGE', 'English')

LANGUAGES = {
    "English": False,
    "Simplified Chinese": False,
    "Traditional Chinese": False,
    "Russian": False,
}

LANGUAGES_TO_CODE = {
    "English": "en",
    "Simplified Chinese": "zh",
    "Traditional Chinese": "zh-hk",
    "Russian": "ru",
}

current_date = datetime.now()
Current_Date = current_date.strftime("%Y-%m-%d")
systemprompt = os.environ.get('SYSTEMPROMPT', prompt.system_prompt.format(LANGUAGE, Current_Date))

import json
import tomllib
import requests
from contextlib import contextmanager

CONFIG_DIR = os.environ.get('CONFIG_DIR', 'user_configs')

@contextmanager
def file_lock(filename):
    if os.name == 'nt':
        import msvcrt
        with open(filename, 'a+') as f:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                yield f
            finally:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except:
                    pass
    else:
        import fcntl
        with open(filename, 'a+') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield f
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

def save_user_config(user_id, config):
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    filename = os.path.join(CONFIG_DIR, f'{user_id}.json')

    with file_lock(filename):
        with open(filename, 'w') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

def load_user_config(user_id):
    filename = os.path.join(CONFIG_DIR, f'{user_id}.json')

    if not os.path.exists(filename):
        return {}

    with file_lock(filename):
        with open(filename, 'r') as f:
            content = f.read()
            if not content.strip():
                return {}
            else:
                return json.loads(content)

def update_user_config(user_id, key, value):
    config = load_user_config(user_id)
    config[key] = value
    save_user_config(user_id, config)

class NestedDict:
    def __init__(self):
        self.data = {}

    def __getitem__(self, key):
        if key not in self.data:
            self.data[key] = NestedDict()
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __str__(self):
        return str(self.data)

    def keys(self):
        return self.data.keys()

class UserConfig:
    def __init__(self,
        user_id: str = None,
        language="English",
        api_url="https://api.groq.com/openai/v1/chat/completions",
        api_key=None,
        engine="llama-3.3-70b-versatile",
        mode="global",
        preferences=None,
        plugins=None,
        languages=None,
        systemprompt=None,
    ):
        self.user_id = user_id
        self.language = language
        self.languages = languages
        self.languages[self.language] = True
        self.api_url = api_url
        self.api_key = api_key
        self.engine = engine
        self.preferences = preferences
        self.plugins = plugins
        self.systemprompt = systemprompt
        self.mode = mode
        self.users = NestedDict()
        self.load_all_configs()
        if "global" not in self.users.keys():
            self.users["global"] = self.get_init_preferences()
            self.users["global"].update(self.preferences)
            self.users["global"].update(self.plugins)
            self.users["global"].update(self.languages)
            for key in list(self.users["global"].keys()):
                update_user_config("global", key, self.users["global"][key])
        self.parameter_name_list = list(self.users["global"].keys())

    def load_all_configs(self):
        if not os.path.exists(CONFIG_DIR):
            return

        for filename in os.listdir(CONFIG_DIR):
            if filename.endswith('.json'):
                user_id = filename[:-5]
                user_config = load_user_config(user_id)
                self.users[user_id] = NestedDict()

                updated_config = False
                for new_plugin, status in self.plugins.items():
                    if new_plugin not in user_config:
                        user_config[new_plugin] = status
                        updated_config = True

                if updated_config:
                    save_user_config(user_id, user_config)

                for key, value in user_config.items():
                    self.users[user_id][key] = value
                    if key == "api_url" and value != self.api_url:
                        self.users[user_id]["api_url"] = self.api_url
                        update_user_config(user_id, "api_url", self.api_url)
                    if key == "api_key" and value != self.api_key:
                        self.users[user_id]["api_key"] = self.api_key
                        update_user_config(user_id, "api_key", self.api_key)
                    if user_id == "global" and key == "systemprompt" and value != self.systemprompt:
                        self.users[user_id]["systemprompt"] = self.systemprompt
                        update_user_config(user_id, "systemprompt", self.systemprompt)

    def get_init_preferences(self):
        return {
            "language": self.language,
            "engine": self.engine,
            "systemprompt": self.systemprompt,
            "api_key": self.api_key,
            "api_url": self.api_url,
        }

    def user_init(self, user_id = None):
        if user_id == None or self.mode == "global":
            user_id = "global"
        self.user_id = user_id
        if self.user_id not in self.users.keys():
            self.users[self.user_id] = self.get_init_preferences()
            self.users[self.user_id].update(self.preferences)
            self.users[self.user_id].update(self.plugins)
            self.users[self.user_id].update(self.languages)
            for key in self.users[self.user_id].keys():
                update_user_config(user_id, key, self.users[self.user_id][key])

    def get_config(self, user_id = None, parameter_name = None):
        if parameter_name not in self.parameter_name_list:
            raise ValueError(f"parameter_name {parameter_name} is not in the parameter_name_list: {self.parameter_name_list}")
        if self.mode == "global":
            return self.users["global"][parameter_name]
        if self.mode == "multiusers":
            self.user_init(user_id)
            return self.users[self.user_id][parameter_name]

    def set_config(self, user_id = None, parameter_name = None, value = None):
        if parameter_name not in self.parameter_name_list:
            raise ValueError(f"parameter_name {parameter_name} is not in the parameter_name_list: {self.parameter_name_list}")
        if self.mode == "global":
            self.users["global"][parameter_name] = value
            update_user_config("global", parameter_name, value)
        if self.mode == "multiusers":
            self.user_init(user_id)
            self.users[self.user_id][parameter_name] = value
            update_user_config(self.user_id, parameter_name, value)

    def extract_plugins_config(self, user_id = None):
        self.user_init(user_id)
        if isinstance(self.users[self.user_id], dict):
            user_data = self.users[self.user_id]
        else:
            user_data = self.users[self.user_id].data
        plugins_config = {key: value for key, value in user_data.items() if key in self.plugins}
        return plugins_config

    def to_json(self, user_id=None):
        def nested_dict_to_dict(nd):
            if isinstance(nd, NestedDict):
                return {k: nested_dict_to_dict(v) for k, v in nd.data.items()}
            return nd

        if user_id:
            serializable_config = nested_dict_to_dict(self.users[user_id])
        else:
            serializable_config = nested_dict_to_dict(self.users)

        return json.dumps(serializable_config, ensure_ascii=False, indent=2)

    def __str__(self):
        return str(self.users)

Users = UserConfig(mode=CHAT_MODE, api_key=API_KEY, api_url=BASE_URL, engine=MODEL, preferences=PREFERENCES, plugins=PLUGINS, language=LANGUAGE, languages=LANGUAGES, systemprompt=systemprompt)

temperature = float(os.environ.get('temperature', '0.5'))

ChatGPTbot, SummaryBot, whisperBot = None, None, None
def InitEngine(chat_id=None):
    global Users, ChatGPTbot, SummaryBot, whisperBot
    api_key = Users.get_config(chat_id, "api_key")
    api_url = Users.get_config(chat_id, "api_url")
    if api_key:
        ChatGPTbot = chatgpt(temperature=temperature, print_log=True, api_url=api_url, api_key=api_key, retry_count=3)
        SummaryBot = chatgpt(temperature=temperature, use_plugins=False, print_log=True, api_url=api_url, api_key=api_key, retry_count=3)
        whisperBot = whisper(api_key=api_key, api_url=api_url)

def update_language_status(language, chat_id=None):
    global Users
    systemprompt = Users.get_config(chat_id, "systemprompt")
    LAST_LANGUAGE = Users.get_config(chat_id, "language")
    Users.set_config(chat_id, "language", language)
    for lang in LANGUAGES:
        Users.set_config(chat_id, lang, False)

    Users.set_config(chat_id, language, True)
    systemprompt = systemprompt.replace(LAST_LANGUAGE, Users.get_config(chat_id, "language"))
    Users.set_config(chat_id, "systemprompt", systemprompt)

InitEngine(chat_id=None)
update_language_status(LANGUAGE)

def get_local_version_info():
    try:
        current_directory = os.path.dirname(os.path.abspath(__file__))
        pyproject_path = os.path.join(current_directory, 'pyproject.toml')
        with open(pyproject_path, 'rb') as f:
            data = tomllib.load(f)
        return data['project']['version']
    except Exception:
        return "unknown"

def get_remote_version_info():
    try:
        url = "https://raw.githubusercontent.com/yym68686/ChatGPT-Telegram-Bot/main/pyproject.toml"
        response = requests.get(url)
        response.raise_for_status()
        data = tomllib.loads(response.text)
        return data['project']['version']
    except Exception:
        return "unknown"

def check_for_updates():
    local_version = get_local_version_info()
    remote_version = get_remote_version_info()

    if local_version == "unknown" or remote_version == "unknown":
        return "Version check failed."

    if local_version == remote_version:
        return local_version
    else:
        return "A new version is available! Please redeploy."

def replace_with_asterisk(string):
    if string:
        if len(string) <= 4:
            return string[0] + '*' * 10
        else:
            return string[:10] + '*' * 10 + string[-2:]
    else:
        return None

def update_info_message(user_id = None):
    api_key = Users.get_config(user_id, "api_key")
    api_url = Users.get_config(user_id, "api_url")
    return "".join([
        f"**🤖 Model:** `{Users.get_config(user_id, 'engine')}`\n\n",
        f"**🔑 API_KEY:** `{replace_with_asterisk(api_key)}`\n\n" if api_key else "",
        f"**🔗 BASE URL:** `{api_url}`\n\n" if api_url else "",
        f"**🛜 WEB HOOK:** `{WEB_HOOK}`\n\n" if WEB_HOOK else "",
        f"**🚰 Tokens usage:** `{get_robot(user_id)[0].tokens_usage[str(user_id)]}`\n\n" if get_robot(user_id)[0] else "",
        f"**🃏 NICK:** `{NICK}`\n\n" if NICK else "",
        f"**📖 Version:** `{check_for_updates()}`\n\n",
    ])

def reset_ENGINE(chat_id, message=None):
    global ChatGPTbot
    api_key = Users.get_config(chat_id, "api_key")
    if message:
        Users.set_config(chat_id, "systemprompt", message)
    systemprompt = Users.get_config(chat_id, "systemprompt")
    if api_key and ChatGPTbot:
        ChatGPTbot.reset(convo_id=str(chat_id), system_prompt=systemprompt)

def get_robot(chat_id = None):
    global ChatGPTbot
    engine = Users.get_config(chat_id, "engine")
    role = "user"
    robot = ChatGPTbot
    api_key = Users.get_config(chat_id, "api_key")
    api_url = Users.get_config(chat_id, "api_url")
    api_url = BaseAPI(api_url=api_url).chat_url

    return robot, role, api_key, api_url

whitelist = os.environ.get('whitelist', None)
if whitelist == "":
    whitelist = None
if whitelist:
    whitelist = [id for id in whitelist.split(",")]

BLACK_LIST = os.environ.get('BLACK_LIST', None)
if BLACK_LIST == "":
    BLACK_LIST = None
if BLACK_LIST:
    BLACK_LIST = [id for id in BLACK_LIST.split(",")]

ADMIN_LIST = os.environ.get('ADMIN_LIST', None)
if ADMIN_LIST == "":
    ADMIN_LIST = None
if ADMIN_LIST:
    ADMIN_LIST = [id for id in ADMIN_LIST.split(",")]
GROUP_LIST = os.environ.get('GROUP_LIST', None)
if GROUP_LIST == "":
    GROUP_LIST = None
if GROUP_LIST:
    GROUP_LIST = [id for id in GROUP_LIST.split(",")]

def delete_model_digit_tail(lst):
    if len(lst) == 2:
        return "-".join(lst)
    for i in range(len(lst) - 1, -1, -1):
        if not lst[i].isdigit():
            if i == len(lst) - 1:
                return "-".join(lst)
            else:
                return "-".join(lst[:i + 1])

def get_status(chatid = None, item = None):
    if item == "PASS_HISTORY":
        return "✅ " if int(Users.get_config(chatid, item)) > 2 else "☑️ "
    return "✅ " if Users.get_config(chatid, item) else "☑️ "

def create_buttons(strings, plugins_status=False, lang="English", button_text=None, Suffix="", chatid=None):
    if plugins_status:
        strings_array = {kv:kv for kv in strings}
    else:
        abbreviation_strings = [delete_model_digit_tail(s.split("-")) for s in strings]
        from collections import Counter
        counter = Counter(abbreviation_strings)
        filtered_counter = {key: count for key, count in counter.items() if count > 1}

        strings_array = {}
        for s in strings:
            if delete_model_digit_tail(s.split("-")) in filtered_counter:
                strings_array[s] = s
            else:
                strings_array[delete_model_digit_tail(s.split('-'))] = s

    if not button_text:
        button_text = {k:{lang:k} for k in strings_array.keys()}
    filtered_strings1 = {k:v for k, v in strings_array.items() if k in button_text and len(button_text[k][lang]) <= 14}
    filtered_strings2 = {k:v for k, v in strings_array.items() if k in button_text and len(button_text[k][lang]) > 14}

    buttons = []
    temp = []

    for k, v in filtered_strings1.items():
        if plugins_status:
            button = InlineKeyboardButton(f"{get_status(chatid, k)}{button_text[k][lang]}", callback_data=k + Suffix)
        else:
            button = InlineKeyboardButton(k, callback_data=v + Suffix)
        temp.append(button)

        if len(temp) == 2:
            buttons.append(temp)
            temp = []

    if temp:
        buttons.append(temp)

    for k, v in filtered_strings2.items():
        if plugins_status:
            button = InlineKeyboardButton(f"{get_status(chatid, k)}{button_text[k][lang]}", callback_data=k + Suffix)
        else:
            button = InlineKeyboardButton(k, callback_data=v + Suffix)
        buttons.append([button])

    return buttons

initial_model = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

def remove_no_text_model(model_list):
    set_models = set()
    for model_item in model_list:
        if "dalle" in model_item or "dall-e" in model_item:
            continue
        if "whisper" in model_item:
            continue
        if "moderation" in model_item:
            continue
        if "embedding" in model_item:
            continue
        set_models.add(model_item)
    return list(set_models)

async def get_initial_model():
    global initial_model
    robot, role, api_key, api_url = get_robot()
    engine = Users.get_config(None, "engine")
    provider = {
        "provider": "openai",
        "base_url": api_url,
        "api": api_key,
        "model": [engine],
        "tools": True,
        "image": True
    }
    initial_model = remove_no_text_model(await update_initial_model(provider))
    if ChatGPTbot:
        robot = ChatGPTbot
        api_key = Users.get_config(None, "api_key")
        api_url = Users.get_config(None, "api_url")
        api_url = BaseAPI(api_url=api_url).chat_url
        provider = {
            "provider": "openai",
            "base_url": api_url,
            "api": api_key,
            "model": [engine],
            "tools": True,
            "image": True
        }
        gpt_initial_model = remove_no_text_model(await update_initial_model(provider))
        initial_model = list(set(gpt_initial_model + initial_model))

# Structure for storing model groups
MODEL_GROUPS = {}
CUSTOM_MODELS_LIST = []

CUSTOM_MODELS = os.environ.get('CUSTOM_MODELS', None)
if CUSTOM_MODELS:
    parts = CUSTOM_MODELS.split(';')
    ungrouped_models = []

    first_part = parts[0].split(',') if parts else []
    for item in first_part:
        item = item.strip()
        if item:
            CUSTOM_MODELS_LIST.append(item)
            if not item.startswith('-'):
                ungrouped_models.append(item)
            print(f"Added to CUSTOM_MODELS_LIST from first part: {item}")

    group_count = 0

    for i in range(1, len(parts)):
        part = parts[i].strip()
        if not part:
            continue

        if ':' in part:
            group_name, models_str = part.split(':', 1)
            group_name = group_name.strip()
            models = [m.strip() for m in models_str.split(',') if m.strip()]
            if group_name and models:
                MODEL_GROUPS[group_name] = models
                for m in models:
                    if m not in CUSTOM_MODELS_LIST:
                        CUSTOM_MODELS_LIST.append(m)
                group_count += 1
        else:
            models = [m.strip() for m in part.split(',') if m.strip()]
            for m in models:
                ungrouped_models.append(m)
                if m not in CUSTOM_MODELS_LIST:
                    CUSTOM_MODELS_LIST.append(m)

    if ungrouped_models:
        if group_count > 0:
            MODEL_GROUPS["OTHERS"] = ungrouped_models
        else:
            MODEL_GROUPS["DEFAULT"] = ungrouped_models
