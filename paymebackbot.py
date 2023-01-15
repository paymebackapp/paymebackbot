import config
import logging
import datetime
import time
import qrcode
from PIL import Image
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

TOKEN =  config.TOKEN
client = MongoClient(config.client)
db = client.get_database('payment_db')

SEND_CONTACT, CHOOSE_DEBT_MODE, OWEDVALUE, ONETOONEFINAL, OWEALLFINAL = range(5)

# Function to simplify unecessary payments. By ChatGPT
def simplify_payments(transactions):
    # Create a dictionary to store the debt owed by each person
    debt = {}
    # Iterate over the transactions
    for t in transactions:
        # If the person paying is not in the debt dictionary, add them with a value of 0
        if t['payer'] not in debt:
            debt[t['payer']] = 0
        # If the person receiving is not in the debt dictionary, add them with a value of 0
        if t['receiver'] not in debt:
            debt[t['receiver']] = 0
        # Add the amount of the transaction to the debt of the person paying
        debt[t['payer']] -= t['amount']
        # Subtract the amount of the transaction from the debt of the person receiving
        debt[t['receiver']] += t['amount']
    # Create a list to store the simplified transactions
    simplified_transactions = []
    # Iterate over the debt dictionary
    for person1 in debt:
        for person2 in debt:
            # If person1 owes person2 money
            if debt[person1] < 0 and debt[person2] > 0:
                # If the absolute value of the debt of person1 is less than the debt of person2
                if abs(debt[person1]) < debt[person2]:
                    # Add a simplified transaction to the list
                    simplified_transactions.append({'payer': person1, 'receiver': person2, 'amount': abs(debt[person1])})
                    # Subtract the paid amount from the debt of person1 and person2
                    debt[person1] += abs(debt[person1])
                    debt[person2] -= abs(debt[person1])
                else:
                    # Add a simplified transaction to the list
                    simplified_transactions.append({'payer': person1, 'receiver': person2, 'amount': debt[person2]})
                    # Subtract the paid amount from the debt of person1 and person2
                    debt[person1] += debt[person2]
                    debt[person2] = 0
    return simplified_transactions

#QRcode related functions are reused from previous projects.
'''
Function to translate QR information dictionary payload to string of characters 
Works for any layers of nested objects (for this case we only have one nested layer ID 26)
'''
def get_info_string(info):
    final_string = '' # Empty string to store the generated output
    for key, value in info.items(): # Loop through the outer dictionary
        if type(value) == dict: # If there is a nested dictionary
            temp_string_length, temp_string = get_info_string(value) #call this function recusively to get the nested info
            # Adds the ID, length and value of the nested object
            final_string += key 
            final_string += temp_string_length
            final_string += temp_string
        else: # Normal value, adds the 3 fields: ID, length, value
            final_string += key
            final_string += str(len(value)).zfill(2)
            final_string += value
    return str(len(final_string)).zfill(2), final_string # Returns the length of the current string and its value

def generatePayNowQR(point_of_initiation,
                    proxy_type,
                    proxy_value,
                    editable,
                    amount,
                    expiry,
                    bill_number
                    ):
       '''
       Nested dictionary that follows the structure of the data object
       dictionary key = data object id, 
       dictionary value = data object value
       Application can also insert new key-value pairs corrosponding to its ID-value in whichever nested layer
       as long as the first and last root ID are 00 and 63 respectively. Order doesnt matter for the rest.
       '''
       info = {"00":"01",
              "01":str(point_of_initiation),
              "26":{"00":"SG.PAYNOW",
                     "01":str(proxy_type),
                     "02":str(proxy_value),
                     "03":str(editable),
                     "04":str(expiry)
                     } ,
              "52":"0000",
              "53":"702",
              "54":str(amount),
              "58":"SG",
              "59":"NA",
              "60":"Singapore",
              "62":{"01":str(bill_number)}
              }
       payload = get_info_string(info)[1] # gets the final string, length is not needed
       payload += '6304' # append ID 63 and length 4 (generated result will always be of length 4)
       crc_value = crc16_ccitt(payload) # calculate CRC checksum
       crc_value = ('{:04X}'.format(crc_value)) #convert into 4 digit uppercase hex
       payload += crc_value # add the CRC checksum result

       # Creating an instance of qrcode
       qr = qrcode.QRCode(
              version = 1, # the size of QR code matrix.
              box_size = 5, # how many pixels is each box of the QR code
              border = 4, # how thick is the border
              error_correction = qrcode.constants.ERROR_CORRECT_H,) # able to damage/cover the QR Code up to a certain percentage. H - 30% 
       qr.add_data(payload)
       qr.make(fit=True) #QR code to fit the entire dimension even when the input data could fit into fewer boxes
       img = qr.make_image(fill_color=(144,19,123), back_color='white') #PayNow purple colour
       
       # Adding PayNow logo to the center
       logo = Image.open('./paynow_logo.png')
       # adjust logo image size 
       basewidth = 85 # adjust this value for logo size
       wpercent = (basewidth/float(logo.size[0]))
       hsize = int((float(logo.size[1])*float(wpercent)))
       logo = logo.resize((basewidth, hsize), Image.Resampling.LANCZOS)
       # set position of logo and paste it 
       pos = ((img.size[0] - logo.size[0]) // 2,
              (img.size[1] - logo.size[1]) // 2)
       img.paste(logo, pos)
       
       img.save('generated_qr.png')
       
def crc16_ccitt(data): 
    crc = 0xFFFF # initial value
    msb = crc >> 8
    lsb = crc & 255
    for c in data:
        x = ord(c) ^ msb
        x ^= (x >> 4)
        msb = (lsb ^ (x >> 3) ^ (x << 4)) & 255
        lsb = (x ^ (x << 5)) & 255
    return (msb << 8) + lsb


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
            transactions_list = []
            members_list = [user_id]
            group_details = {
                'group_id':group_id,
                'members': members_list,
                'transaction_details':transactions_list
            }
            transactions_info.update_one({'group_id':group_id}, {'$set':group_details}, upsert=True)
            context.bot.send_message(group_id, text="Session started by "+ name +  "! Other members please use /join to join the session.")
        else: 
            context.bot.send_message(group_id, text="There is already an active session!")

def join(update,context):
    chat_type = update.message.chat.type
    group_id = update.message.chat.id
    user_id = update.message.from_user.id
    name = update.message.from_user.first_name
    
    if chat_type == 'private':
        update.message.reply_text('Please send all your commands in your group chat!')
        return ConversationHandler.END

    transactions_info = db.transactions_info
    group_info = transactions_info.find_one({'group_id':group_id})
    if group_info == None:
        update.message.reply_text('There is currently no active session going on! Use /create_session to start a new one.')
        return ConversationHandler.END
    else:
        members_list = group_info['members']
        members_list.append(user_id)
        group_details = {
            'members': members_list
        }
        transactions_info.update_one({'group_id':group_id}, {'$set':group_details}, upsert=True)
                
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
            if group_info == None:
                update.message.reply_text('There is no active session going on!')
                return ConversationHandler.END
            else:
                keyboard = [[InlineKeyboardButton('I owe people', callback_data='I owe people'),
                            InlineKeyboardButton('People owe me', callback_data='People owe me')]]
                reply_markup = InlineKeyboardMarkup(keyboard)    
                context.bot.send_message(user_id,'Choose your mode:', reply_markup=reply_markup)
                context.user_data['group_id'] = group_id
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
    group_id = context.user_data['group_id'] 
    if query.data == 'I owe people':
        transactions_info = db.transactions_info
        group_info = transactions_info.find_one({'group_id':group_id})
        members_list = group_info['members']
        keyboard = []
        users_info = db.users_info
        
        for member_user_id in members_list: # in the form of user_id
            user = users_info.find_one({'user_id':member_user_id})
            name = user['name']
            keyboard.append([InlineKeyboardButton(name, callback_data=member_user_id)])
        # keyboard.append([InlineKeyboardButton('Cancel', callback_data='Cancel')])
        reply_markup = InlineKeyboardMarkup(keyboard)  
        context.bot.send_message(user_id,'Who do you owe $ to?', reply_markup=reply_markup)
        return OWEDVALUE
    elif query.data == 'People owe me':
        context.bot.send_message(user_id,'Enter the total bill and tax percentage. Eg: 100,18')
        return OWEALLFINAL

def owed_value(update,context):
    query = update.callback_query
    user_id = query.from_user.id
    users_info = db.users_info
    creditor_info = users_info.find_one({'user_id':int(query.data)})

    creditor_name = creditor_info['name']
    query.edit_message_text(text="Selected creditor: {}".format(creditor_name))
    group_id = context.user_data['group_id']
    context.user_data['creditor'] = int(query.data)
    context.bot.send_message(user_id,'How much do you owe?')
    return ONETOONEFINAL

def one_to_one_final(update,context):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    name = update.message.from_user.first_name
    owed_amount = float(update.message.text)
    transactions_info = db.transactions_info
    group_id = context.user_data['group_id']
    group_info = transactions_info.find_one({'group_id':group_id})
    transactions_list = group_info['transaction_details']
    transactions_list.append({'payer': user_id, 'receiver': context.user_data['creditor'], 'amount': owed_amount})
    group_details = {
            'transaction_details': transactions_list
        }
    transactions_info.update_one({'group_id':group_id}, {'$set':group_details}, upsert=True)
    context.user_data.clear()
    context.bot.send_message(user_id,'Transaction recorded!')
    return ConversationHandler.END

def owe_all_final(update,context):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    name = update.message.from_user.first_name
    owed_amount = update.message.text
    total_amount, tax = owed_amount.split(",")
    total_amount = float(total_amount)
    tax = float(tax)

    transactions_info = db.transactions_info
    group_id = context.user_data['group_id']
    group_info = transactions_info.find_one({'group_id':group_id})
    transactions_list = group_info['transaction_details']
    members_list = group_info['members']
    for member_user_id in members_list: # in the form of user_id
        transactions_list.append({'payer': member_user_id, 'receiver': user_id, 'amount': total_amount/len(members_list)})
    group_details = {
            'transaction_details': transactions_list
        }
    transactions_info.update_one({'group_id':group_id}, {'$set':group_details}, upsert=True)

    context.bot.send_message(user_id,'Transaction recorded!')
    return ConversationHandler.END

def view_transactions(update, context):
    chat_type = update.message.chat.type
    group_id = update.message.chat.id
    user_id = update.message.from_user.id
    name = update.message.from_user.first_name
    
    if chat_type == 'private':
        update.message.reply_text('Please send all your commands in your group chat!')
        return ConversationHandler.END

    transactions_info = db.transactions_info
    group_info = transactions_info.find_one({'group_id':group_id})
    transactions_list = group_info['transaction_details']

    context.bot.send_message(group_id,transactions_list)

def end_session(update,context):
    group_id = update.message.chat.id
    users_info = db.users_info
    transactions_info = db.transactions_info
    group_info = transactions_info.find_one({'group_id':group_id})
    transactions_list = group_info['transaction_details']
    simplified_transactions = simplify_payments(transactions_list)
    if simplified_transactions != []:
        for transaction in simplified_transactions:
            receiver_id = transaction['receiver']
            payer_id = transaction['payer']
            receiver_info = users_info.find_one({'user_id':receiver_id})
            receiver_number = receiver_info['phone_number']
            receiver_name = receiver_info['name']

            point_of_initiation = '12'
            proxy_type = '0'
            proxy_value = receiver_number
            editable = '1'
            amount  = transaction['amount']
            expiry = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime('%Y%m%d') # one day later, YYYMMDD
            bill_number = 'O$P$'
            generatePayNowQR(point_of_initiation,
                proxy_type,
                proxy_value,
                editable,
                amount,
                expiry,
                bill_number
                )
            keyboard=[[InlineKeyboardButton("Open PayLah!", url="https://www.dbs.com.sg/personal/mobile/paylink/index.html?tranRef=")]]
            reply_markup = InlineKeyboardMarkup(keyboard)    
            context.bot.send_message(payer_id, text="Please pay "+receiver_name+" $" + str(amount), reply_markup=reply_markup)
            context.bot.send_photo(payer_id, photo=open('generated_qr.png', 'rb'))
    transactions_info.delete_one({'group_id':group_id})
    context.bot.send_message(group_id, "Session ended!")

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
    dp.add_handler(CommandHandler("view_transactions", view_transactions))
    dp.add_handler(CommandHandler("end_session", end_session))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start),CommandHandler("add_debts", add_debts)],

        states={
            SEND_CONTACT : [MessageHandler(Filters.contact, send_contact)],
            CHOOSE_DEBT_MODE : [CallbackQueryHandler(choose_debt_mode)],
            OWEDVALUE : [CallbackQueryHandler(owed_value)],
            ONETOONEFINAL : [MessageHandler(Filters.text, one_to_one_final)],
            OWEALLFINAL : [MessageHandler(Filters.text, owe_all_final)],
            
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