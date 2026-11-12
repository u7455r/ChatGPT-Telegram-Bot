import re
import sys
sys.dont_write_bytecode = True
import base64
import logging
import traceback
import utils.decorators as decorators

from md2tgmd.src.md2tgmd import escape, split_code, replace_all
from aient.aient.utils.scripts import Document_extract
from aient.aient.core.utils import get_engine, get_image_message, get_text_message

# Groq / Llama HTTP Interceptor Patch (100% Bypass Model Validation)
import json as _json
import httpx as _httpx
import aient.aient.core.utils as aient_utils

_orig_get_engine = aient_utils.get_engine
def _patched_get_engine(provider, endpoint=None, original_model=""):
    engine, stream = _orig_get_engine(provider, endpoint, original_model)
    base_url = str(provider.get("base_url", "")) if isinstance(provider, dict) else ""
    if "groq.com" in base_url or "llama" in str(original_model).lower():
        return "gpt", stream
    return engine, stream

aient_utils.get_engine = _patched_get_engine
get_engine = _patched_get_engine

_orig_async_send = _httpx.AsyncClient.send
async def _patched_async_send(self, request, *args, **kwargs):
    if "groq.com" in str(request.url) and request.content:
        try:
            body = _json.loads(request.content.decode("utf-8"))
            if "model" in body:
                import config as _cfg
                configured_model = _cfg.Users.get_config(None, "engine")
                body["model"] = "llama-3.3-70b-versatile" if (not configured_model or "gpt" in configured_model) else configured_model
                new_content = _json.dumps(body).encode("utf-8")
                request.headers["content-length"] = str(len(new_content))
                request._content = new_content
        except Exception:
            pass
    return await _orig_async_send(self, request, *args, **kwargs)

_httpx.AsyncClient.send = _patched_async_send

import config
from config import (
    WEB_HOOK,
    PORT,
    BOT_TOKEN,
    GET_MODELS,
    Users,
    PREFERENCES,
    LANGUAGES,
    PLUGINS,
    RESET_TIME,
    get_robot,
    reset_ENGINE,
    get_current_lang,
    update_info_message,
    update_menu_buttons,
    remove_no_text_model,
    update_initial_model,
    update_models_buttons,
    update_language_status,
    update_first_buttons_message,
    get_all_available_models,
    get_model_groups,
    CUSTOM_MODELS_LIST,
    MODEL_GROUPS,
    get_initial_model,
)

from utils.i18n import strings
from utils.scripts import GetMesageInfo, safe_get, is_emoji

from telegram.constants import ChatAction
from telegram import BotCommand, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputMediaPhoto, InlineKeyboardButton
from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, CallbackQueryHandler, Application, AIORateLimiter, InlineQueryHandler, ContextTypes
from datetime import timedelta

import asyncio
lock = asyncio.Lock()
event = asyncio.Event()
stop_event = asyncio.Event()
time_out = 600
target_convo_id = None
reset_mess_id = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

class SpecificStringFilter(logging.Filter):
    def __init__(self, specific_string):
        super().__init__()
        self.specific_string = specific_string

    def filter(self, record):
        return self.specific_string not in record.getMessage()

specific_string = "httpx.RemoteProtocolError: Server disconnected without sending a response."
my_filter = SpecificStringFilter(specific_string)

update_logger = logging.getLogger("telegram.ext.Updater")
update_logger.addFilter(my_filter)
update_logger = logging.getLogger("root")
update_logger.addFilter(my_filter)

from collections import defaultdict
message_cache = defaultdict(lambda: [])
time_stamps = defaultdict(lambda: [])

def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.job_queue:
        return False
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

async def scheduled_function(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    reset_ENGINE(job.name)

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
@decorators.APICheck
async def command_bot(update, context, title="", has_command=True):
    stop_event.clear()
    message, rawtext, image_url, chatid, messageid, reply_to_message_text, update_message, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text = await GetMesageInfo(update, context)

    if has_command == False or len(context.args) > 0:
        if has_command:
            message = ' '.join(context.args)
        pass_history = Users.get_config(convo_id, "PASS_HISTORY")
        if message == None:
            message = voice_text
        if message and len(message) == 1 and is_emoji(message):
            return

        message_has_nick = False
        botNick = config.NICK.lower() if config.NICK else None
        if rawtext and rawtext.split()[0].lower() == botNick:
            message_has_nick = True

        if message_has_nick and update_message.reply_to_message and update_message.reply_to_message.caption and not message:
            message = update_message.reply_to_message.caption

        if message:
            if pass_history >= 3:
                remove_job_if_exists(convo_id, context)
                if context.job_queue:
                    context.job_queue.run_once(
                        scheduled_function,
                        when=timedelta(seconds=RESET_TIME),
                        chat_id=chatid,
                        name=convo_id
                    )

            bot_info_username = None
            try:
                bot_info = await context.bot.get_me(read_timeout=time_out, write_timeout=time_out, connect_timeout=time_out, pool_timeout=time_out)
                bot_info_username = bot_info.username
            except Exception as e:
                print("error:", e)
                if update_message.reply_to_message and update_message.reply_to_message.from_user:
                    bot_info_username = update_message.reply_to_message.from_user.username

            if update_message.reply_to_message \
            and update_message.from_user.is_bot == False \
            and (update_message.reply_to_message.from_user.username == bot_info_username or message_has_nick):
                if update_message.reply_to_message.from_user.is_bot and Users.get_config(convo_id, "TITLE") == True:
                    message = message + "\n" + '\n'.join(reply_to_message_text.split('\n')[1:])
                else:
                    if reply_to_message_text:
                        message = message + "\n" + reply_to_message_text
                    if reply_to_message_file_content:
                        message = message + "\n" + reply_to_message_file_content
            elif update_message.reply_to_message and update_message.reply_to_message.from_user.is_bot \
            and update_message.reply_to_message.from_user.username != bot_info_username:
                return

            robot, role, api_key, api_url = get_robot(convo_id)
            engine = Users.get_config(convo_id, "engine")

            if Users.get_config(convo_id, "LONG_TEXT"):
                async with lock:
                    message_cache[convo_id].append(message)
                    import time
                    time_stamps[convo_id].append(time.time())
                    if len(message_cache[convo_id]) == 1:
                        if len(message_cache[convo_id][0]) > 800:
                            event.clear()
                        else:
                            event.set()
                    else:
                        return
                try:
                    await asyncio.wait_for(event.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass

                message = "\n".join(message_cache[convo_id])
                message_cache[convo_id] = []
                time_stamps[convo_id] = []

            if Users.get_config(convo_id, "TITLE"):
                title = f"`🤖️ {engine}`\n\n"
            if Users.get_config(convo_id, "REPLY") == False:
                messageid = None

            engine_type, _ = get_engine({"base_url": api_url}, endpoint=None, original_model=engine)
            if robot.__class__.__name__ == "chatgpt":
                engine_type = "gpt"
            if image_url:
                message_list = []
                image_message = await get_image_message(image_url, engine_type)
                text_message = await get_text_message(message, engine_type)
                message_list.append(text_message)
                message_list.append(image_message)
                message = message_list
            elif file_url:
                image_url = file_url
                message = await Document_extract(file_url, image_url, engine_type) + message

            await getChatGPT(update_message, context, title, robot, message, chatid, messageid, convo_id, message_thread_id, pass_history, api_key, api_url, engine)
    else:
        await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['message_command_text_none'][get_current_lang(convo_id)]),
            parse_mode='MarkdownV2',
            reply_to_message_id=messageid,
        )

async def delete_message(update, context, messageid = [], delay=60):
    await asyncio.sleep(delay)
    if isinstance(messageid, list):
        for mid in messageid:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass

from telegram.error import Forbidden, TelegramError
async def is_bot_blocked(bot, user_id: int) -> bool:
    try:
        await bot.send_chat_action(chat_id=user_id, action="typing")
        return False
    except Forbidden:
        return True
    except TelegramError:
        return False

async def getChatGPT(update_message, context, title, robot, message, chatid, messageid, convo_id, message_thread_id, pass_history=0, api_key=None, api_url=None, engine = None):
    lastresult = title
    text = message
    result = ""
    tmpresult = ""
    modifytime = 0
    time_out = 600
    image_has_send = 0
    model_name = engine
    language = Users.get_config(convo_id, "language")
    system_prompt = Users.get_config(convo_id, "systemprompt")
    plugins = Users.extract_plugins_config(convo_id)

    Frequency_Modification = 20
    if "gpt-5" in model_name:
        Frequency_Modification = 25
    if message_thread_id or str(convo_id).startswith("-"):
        Frequency_Modification = 35
    if "gemini" in model_name:
        Frequency_Modification = 1

    if not await is_bot_blocked(context.bot, chatid):
        answer_messageid = (await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['message_think'][get_current_lang(convo_id)]),
            parse_mode='MarkdownV2',
            reply_to_message_id=messageid,
        )).message_id
    else:
        return

    try:
        async for data in robot.ask_stream_async(text, convo_id=convo_id, pass_history=pass_history, model=model_name, language=language, api_url=api_url, api_key=api_key, system_prompt=system_prompt, plugins=plugins):
            if stop_event.is_set() and convo_id == target_convo_id and answer_messageid < reset_mess_id:
                return
            if "message_search_stage_" not in data:
                result = result + data
            image_match = re.search(r"![image]\(data:image\/png;base64,([a-zA-Z0-9+/=]+)\)", result)
            if image_match and image_has_send == 0:
                base64_str = image_match.group(1)
                try:
                    img_url = base64.b64decode(base64_str)
                    media_group = [InputMediaPhoto(media=img_url)]
                    await context.bot.send_media_group(
                        chat_id=chatid,
                        media=media_group,
                        message_thread_id=message_thread_id,
                        reply_to_message_id=messageid,
                    )
                    result = result.replace(image_match.group(0), "")
                    image_has_send = 1
                except Exception as e:
                    logger.warning(f"Could not process base64 image: {e}")
                continue
            if result.strip().startswith("![image](data:image/") and image_has_send:
                await context.bot.delete_message(chat_id=chatid, message_id=answer_messageid)
                break
            tmpresult = result
            if re.sub(r"```", '', result.split("\n")[-1]).count("`") % 2 != 0:
                tmpresult = result + "`"
            if sum([line.strip().startswith("```") for line in result.split('\n')]) % 2 != 0:
                tmpresult = tmpresult + "\n```"
            tmpresult = title + tmpresult
            if "message_search_stage_" in data:
                tmpresult = strings[data][get_current_lang(convo_id)]
            history = robot.conversation.get(convo_id, [])
            if safe_get(history, -2, "tool_calls", 0, 'function', 'name') == "generate_image" and not image_has_send and safe_get(history, -1, 'content'):
                image_result = history[-1]['content'].split('\n\n')[1]
                await context.bot.send_photo(chat_id=chatid, photo=image_result, reply_to_message_id=messageid)
                image_has_send = 1
            modifytime = modifytime + 1

            split_len = 3500
            if len(tmpresult) > split_len and Users.get_config(convo_id, "LONG_TEXT_SPLIT"):
                Frequency_Modification = 40
                replace_text = replace_all(tmpresult, r"(```[\D\d\s]+?```)", split_code)
                if "@|@|@|@" in replace_text:
                    split_messages = replace_text.split("@|@|@|@")
                    send_split_message = split_messages[0]
                    result = split_messages[1][:-4]
                else:
                    if replace_text.strip().endswith("```"):
                        replace_text = replace_text.strip()[:-4]
                    split_messages_new = []
                    split_messages = replace_text.split("```")
                    for index, item in enumerate(split_messages):
                        if index % 2 == 1:
                            item = "```" + item
                            if index != len(split_messages) - 1:
                                item = item + "```"
                            split_messages_new.append(item)
                        if index % 2 == 0:
                            item_split_new = []
                            item_split = item.split("\n\n")
                            for sub_index, sub_item in enumerate(item_split):
                                if sub_index % 2 == 1:
                                    sub_item = "\n\n" + sub_item
                                    if sub_index != len(item_split) - 1:
                                        sub_item = sub_item + "\n\n"
                                    item_split_new.append(sub_item)
                                if sub_index % 2 == 0:
                                    item_split_new.append(sub_item)
                            split_messages_new.extend(item_split_new)

                    split_index = 0
                    for index, _ in enumerate(split_messages_new):
                        if len("".join(split_messages_new[:index])) < split_len:
                            split_index += 1
                            continue
                        else:
                            break
                    send_split_message = ''.join(split_messages_new[:split_index])
                    matches = re.findall(r"(```.*?\n)", send_split_message)
                    if len(matches) % 2 != 0:
                        send_split_message = send_split_message + "```\n"
                    tmp = ''.join(split_messages_new[split_index:])
                    if tmp.strip().endswith("```"):
                        result = tmp[:-4]
                    else:
                        result = tmp
                    matches = re.findall(r"(```.*?\n)", send_split_message)
                    result_matches = re.findall(r"(```.*?\n)", result)
                    if len(result_matches) > 0 and result_matches[0].startswith("```\n") and len(result_matches) >= 2:
                        result = matches[-2] + result

                title = ""
                if lastresult != escape(send_split_message, italic=False):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chatid,
                            message_id=answer_messageid,
                            text=escape(send_split_message, italic=False),
                            parse_mode='MarkdownV2',
                            disable_web_page_preview=True,
                            read_timeout=time_out,
                            write_timeout=time_out,
                            pool_timeout=time_out,
                            connect_timeout=time_out
                        )
                        lastresult = escape(send_split_message, italic=False)
                    except Exception as e:
                        if "parse entities" in str(e):
                            await context.bot.edit_message_text(
                                chat_id=chatid,
                                message_id=answer_messageid,
                                text=send_split_message,
                                disable_web_page_preview=True,
                                read_timeout=time_out,
                                write_timeout=time_out,
                                pool_timeout=time_out,
                                connect_timeout=time_out
                            )
                answer_messageid = (await context.bot.send_message(
                    chat_id=chatid,
                    message_thread_id=message_thread_id,
                    text=escape(strings['message_think'][get_current_lang(convo_id)]),
                    parse_mode='MarkdownV2',
                    reply_to_message_id=messageid,
                )).message_id

            now_result = escape(tmpresult, italic=False)
            if now_result and (modifytime % Frequency_Modification == 0 and lastresult != now_result) or "message_search_stage_" in data:
                try:
                    await context.bot.edit_message_text(chat_id=chatid, message_id=answer_messageid, text=now_result, parse_mode='MarkdownV2', disable_web_page_preview=True, read_timeout=time_out, write_timeout=time_out, pool_timeout=time_out, connect_timeout=time_out)
                    lastresult = now_result
                except Exception:
                    continue
    except Exception as e:
        traceback.print_exc()
        api_key = Users.get_config(convo_id, "api_key")
        systemprompt = Users.get_config(convo_id, "systemprompt")
        if api_key:
            robot.reset(convo_id=convo_id, system_prompt=systemprompt)
        if "parse entities" in str(e):
            await context.bot.edit_message_text(chat_id=chatid, message_id=answer_messageid, text=tmpresult, disable_web_page_preview=True, read_timeout=time_out, write_timeout=time_out, pool_timeout=time_out, connect_timeout=time_out)
        else:
            tmpresult = f"{tmpresult}\n\n`{e}`"

    if image_has_send == 0:
        image_extensions = r'(https?://[^\s<>\"()]+(?:\.(?:webp|jpg|jpeg|png|gif)|/image)[^\s<>\"()]*)'
        image_urls = re.findall(image_extensions, tmpresult, re.IGNORECASE)
        image_urls_result = [url[0] if isinstance(url, tuple) else url for url in image_urls]
        if image_urls_result:
            try:
                image_urls_result = image_urls_result[:10]
                media_group = [InputMediaPhoto(media=img_url) for img_url in image_urls_result]
                await context.bot.send_media_group(
                    chat_id=chatid,
                    media=media_group,
                    message_thread_id=message_thread_id,
                    reply_to_message_id=messageid,
                )
            except Exception as e:
                logger.warning(f"Failed to send image(s): {str(e)}")

    now_result = escape(tmpresult, italic=False)
    if lastresult != now_result and answer_messageid:
        if "Can't parse entities: can't find end of code entity at byte offset" in tmpresult:
            await update_message.reply_text(tmpresult)
        elif now_result:
            try:
                await context.bot.edit_message_text(
                    chat_id=chatid,
                    message_id=answer_messageid,
                    text=now_result,
                    parse_mode='MarkdownV2',
                    disable_web_page_preview=True,
                    read_timeout=time_out,
                    write_timeout=time_out,
                    pool_timeout=time_out,
                    connect_timeout=time_out
                )
            except Exception as e:
                if "parse entities" in str(e):
                    await context.bot.edit_message_text(
                        chat_id=chatid,
                        message_id=answer_messageid,
                        text=tmpresult,
                        disable_web_page_preview=True,
                        read_timeout=time_out,
                        write_timeout=time_out,
                        pool_timeout=time_out,
                        connect_timeout=time_out
                    )

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def reset_chat(update, context):
    global target_convo_id, reset_mess_id
    _, _, _, chatid, messageid, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    stop_event.set()
    target_convo_id = convo_id
    reset_mess_id = messageid
    message = ' '.join(context.args)
    reset_ENGINE(convo_id, message)
    remove_job_if_exists(convo_id, context)
    await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(strings['message_reset'][get_current_lang(convo_id)]),
        parse_mode='MarkdownV2',
    )

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def info(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    message = update_info_message(convo_id)
    await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(message, italic=False),
        parse_mode='MarkdownV2',
        disable_web_page_preview=True,
    )

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def start(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    message, reply_markup = update_first_buttons_message(convo_id)
    await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(message, italic=False),
        parse_mode='MarkdownV2',
        reply_markup=reply_markup,
    )

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def model(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    if len(context.args) > 0:
        model_name = context.args[0]
        Users.set_config(convo_id, "engine", model_name)
        await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(f"Model switched to: `{model_name}`", italic=False),
            parse_mode='MarkdownV2',
        )
        return
    reply_markup = update_models_buttons(convo_id)
    await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(strings['message_model'][get_current_lang(convo_id)], italic=False),
        parse_mode='MarkdownV2',
        reply_markup=reply_markup,
    )

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def settings(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    reply_markup = update_menu_buttons(convo_id)
    await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(strings['message_settings'][get_current_lang(convo_id)], italic=False),
        parse_mode='MarkdownV2',
        reply_markup=reply_markup,
    )

async def button_press(update, context):
    query = update.callback_query
    await query.answer()
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    data = query.data
    if data in get_all_available_models():
        Users.set_config(convo_id, "engine", data)
        await query.edit_message_text(
            text=escape(f"Model switched to: `{data}`", italic=False),
            parse_mode='MarkdownV2',
        )
    elif data in PREFERENCES or data in PLUGINS:
        current_val = Users.get_config(convo_id, data)
        if data == "PASS_HISTORY":
            new_val = 0 if int(current_val) > 2 else 9999
        else:
            new_val = not current_val
        Users.set_config(convo_id, data, new_val)
        await query.edit_message_reply_markup(reply_markup=update_menu_buttons(convo_id))
    elif data in LANGUAGES:
        update_language_status(data, convo_id)
        await query.edit_message_reply_markup(reply_markup=update_menu_buttons(convo_id))

async def inlinequery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query.query
    if not query:
        return
    results = [
        InlineQueryResultArticle(
            id="1",
            title="Ask AI",
            input_message_content=InputTextMessageContent(query),
        )
    ]
    await update.inline_query.answer(results)

async def post_init(application: Application) -> None:
    if GET_MODELS:
        try:
            await get_initial_model()
        except Exception as e:
            logger.warning(f"Failed to fetch initial models: {e}")
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("reset", "Reset conversation history"),
        BotCommand("model", "Select AI model"),
        BotCommand("settings", "Configure bot settings"),
        BotCommand("info", "Show current bot configuration"),
    ])

def main():
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .rate_limiter(AIORateLimiter(max_retries=3))
        .post_init(post_init)
        .connect_timeout(60)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(60)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_chat))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("model", model))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("chat", lambda u, c: command_bot(u, c, has_command=True)))
    application.add_handler(CallbackQueryHandler(button_press))
    application.add_handler(InlineQueryHandler(inlinequery))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, lambda u, c: command_bot(u, c, has_command=False)))

    if WEB_HOOK:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEB_HOOK}/{BOT_TOKEN}",
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
