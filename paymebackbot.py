import logging
import datetime
import time
from telegram import (Poll, ParseMode, KeyboardButton, KeyboardButtonPollType,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode)
from telegram.ext import (Updater, CommandHandler, PollAnswerHandler, PollHandler, MessageHandler,
                          Filters, ConversationHandler, CallbackQueryHandler)
from telegram.error import (TelegramError, Unauthorized, BadRequest, 
                            TimedOut, ChatMigrated, NetworkError)
from telegram.utils.helpers import mention_html

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)
from pymongo import MongoClient

TOKEN =  '5896599202:AAHtcRjzImV87dKOBPcU53tFOlBkOxfu4-4'
client = MongoClient("mongodb+srv://capoon:capoon@paymebackcluster0.pgoteoe.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('payment_db')

SEND_CONTACT, CHOOSE_DEBT_MODE = range(2)

def start(update, context):
    """Inform user about what this bot can do"""
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    name = update.message.from_user.first_name
    
    update.message.reply_text('Hi '+ name + ', welcome to <u><b>O$P$</b></u>! This bot makes keeping track of debts convenient and simple!'
                                ' Send all your commands in <i>your own telegram group</i>.\n\n'
                                '<b>List of commands:</b>\n'
                                '/create_session - starts a new record in the group\n'
                                '/end_session - ends the record and collate payments\n'
                                '/cancel_session - cancels the record in the group\n'
                                '/add_receipt - add a payment event\n'
                                '/remove_receipt - deletes your existing payment\n'
                                '/view_debts - checks the current list of payments', parse_mode=ParseMode.HTML)

    keyboard=[[KeyboardButton(text="Send Contact", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard)
    update.message.reply_text("Please send your contact for the bot to work.",reply_markup = reply_markup)
    return SEND_CONTACT

def send_contact(update, context):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    name = update.message.from_user.first_name
    contact = update.message.contact
    phone = contact.phone_number

    
    users_info = db.users_info
    account_info = users_info.find_one({'user_id':user_id})
    if account_info == None:
        localtime = time.localtime(time.time())
        date_now = str(localtime.tm_mday)+'/'+str(localtime.tm_mon)+'/'+str(localtime.tm_year)
        time_now = str(localtime.tm_hour)+':'+str(localtime.tm_min)+':'+str(localtime.tm_sec)
        time_stamp = date_now + ' ' + time_now
        new_user = {
            'user_id':user_id,
            'name':name,
            'username':username,
            'date_joined': time_stamp,
            'phone_number': phone
        }
        users_info.update_one({'user_id':user_id}, {'$set':new_user}, upsert=True)
    context.bot.send_message(user_id, text="Contact number updated!", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def create_session(update, context):
    chat_type = update.message.chat.type
    group_id = update.message.chat.id
    user_id = update.message.from_user.id
    name = update.message.from_user.first_name
    
    if chat_type == 'private':
        update.message.reply_text('Please send all your commands in your group chat!')
        return ConversationHandler.END
    else:
        transactions_info = db.transactions_info
        group_info = transactions_info.find_one({'group_id':group_id})
        if group_info == None:
            transactions = []
            members = [user_id]
            group_details = {
                'group_id':group_id,
                'members': members,
                'transaction_details':transactions
            }
            transactions_info.update_one({'group_id':group_id}, {'$set':group_details}, upsert=True)
            context.bot.send_message(group_id, text="Session started! Use /add_debts to add debts owed.")
        else: 
            context.bot.send_message(group_id, text="There is already an active session!")
        
def add_debts(update,context):
    chat_type = update.message.chat.type
    group_id = update.message.chat.id
    user_id = update.message.from_user.id
    name = update.message.from_user.first_name
    
    if chat_type == 'private':
        update.message.reply_text('Please send all your commands in your group chat!')
        return ConversationHandler.END
    else:
        try:#unauthorised
            transactions_info = db.transactions_info
            group_info = transactions_info.find_one({'group_id':group_id})
            if account_info == None:
                update.message.reply_text('There is no active session going on!')
                return ConversationHandler.END
            else:
                keyboard = [[InlineKeyboardButton('I owe people', callback_data='I owe people'),
                            InlineKeyboardButton('People owe me', callback_data='People owe me')]]
                reply_markup = InlineKeyboardMarkup(keyboard)    
                context.bot.send_message(user_id,'Choose your mode:', reply_markup=reply_markup)
                return CHOOSE_DEBT_MODE

        except Unauthorized:
            keyboard=[[InlineKeyboardButton("Start chat", url="https://t.me/paymeback_bot")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("Please start a private chat with me first.",reply_markup = reply_markup)
            return ConversationHandler.END

def choose_debt_mode(update,context):
    query = update.callback_query
    user_id = query.from_user.id
    query.edit_message_text(text="Selected mode: {}".format(query.data))
    group_id = context.user_data['group_train_start']        
    context.bot_data[group_id]['mode'] = query.data

def timeout(update, context):
    try:
        user_id = update.message.from_user.id
    except:
        query = update.callback_query
        user_id = query.from_user.id
    
    context.bot.send_message(user_id, 'Operation cancelled. You took too long to respond...\nWaiting for christmas ah')
    return ConversationHandler.END

def main():
    # Create the Updater and pass it your bot's token.
    # Make sure to set use_context=True to use the new context based callbacks
    # Post version 12 this will no longer be necessary
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("create_session", create_session))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start),CommandHandler("add_debts", add_debts)],

        states={
            SEND_CONTACT : [MessageHandler(Filters.contact, send_contact)],
            CHOOSE_DEBT_MODE : [CallbackQueryHandler(choose_debt_mode)],
            ConversationHandler.TIMEOUT : [MessageHandler(Filters.command, timeout),CallbackQueryHandler(timeout)]
        },

        fallbacks=[CommandHandler("start", start), CommandHandler("add_debts", add_debts)
                    ],
        per_chat = False,
        conversation_timeout=30
    )
    dp.add_handler(conv_handler)


    # Start the Bot
    updater.start_polling()

    # Run the bot until the user presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT
    updater.idle()


if __name__ == '__main__':
    main()