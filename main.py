import os
import sqlite3
import logging
import multiprocessing
import asyncio
from telegram import Bot, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)

# Main Bot Token
TOKEN = "8950125075:AAGmSWaiWuAO2aLyyl17CPohHil7OI3K0KQ"

if not TOKEN:
    raise ValueError(
        "BOT_TOKEN environment variable is missing! "
        "Set it before running (do NOT hardcode it in the script)."
    )

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Conversation state for cloning
CLONE_TOKEN = 1

def init_db(db_name="chat_bot.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    # Table for users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)
    # Table for storing media files sent to the bot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_store (
            media_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            sender_name TEXT,
            file_id TEXT NOT NULL,
            caption TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Table for tracking cloned bots (only used in main db)
    if db_name == "chat_bot.db":
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cloned_bots (
                bot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                bot_token TEXT UNIQUE,
                bot_username TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False, db_name="chat_bot.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = None
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()
    if commit:
        conn.commit()
    conn.close()
    return result

# Initialize main database
init_db("chat_bot.db")

def get_db_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.bot_data.get("db_name", "chat_bot.db")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = get_db_name(context)
    user_id = update.effective_user.id
    default_name = f"User_{str(user_id)[-4:]}"
    db_execute(
        "INSERT INTO users (user_id, display_name) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET is_active = 1",
        (user_id, default_name),
        commit=True,
        db_name=db_name,
    )
    user_data = db_execute(
        "SELECT display_name FROM users WHERE user_id = ?",
        (user_id,),
        fetchone=True,
        db_name=db_name,
    )
    current_name = user_data[0] if user_data else default_name
    welcome_msg = (
        f"Welcome to the Anonymous Group Chat!\n\n"
        f"Your current display name is: *{current_name}*\n"
        f"To change it, use: `/setmyname YourName`\n"
        f"To view chat statistics, use: `/leaderboard`\n"
        f"To sync/download all shared media, use: `/syncmedia`\n"
        f"To clone and create your own bot, use: `/clone`\n"
        f"To view all cloned bots, use: `/clonedbot`\n"
        f"To see all commands, use: `/help`\n\n"
        f"Just send any message or photo here, and it will be broadcasted to everyone."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Anonymous Chat Bot - Help Menu* 🤖\n\n"
        "Here are the available commands you can use:\n\n"
        "🔹 `/start` - Start the bot and register your profile.\n"
        "🔹 `/setmyname <NewName>` - Change your anonymous display name (up to 30 chars).\n"
        "🔹 `/leaderboard` - View top chatters and message counts.\n"
        "🔹 `/syncmedia` - Retrieve and download all media shared in the chat.\n"
        "🔹 `/clone` - Create your own identical bot using your BotFather token!\n"
        "🔹 `/clonedbot` - View a list of all deployed cloned bots.\n"
        "🔹 `/help` - Show this help menu.\n\n"
        "💬 *Broadcasting:* Send any text or photo to broadcast it anonymously!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = get_db_name(context)
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: `/setmyname YourNewName`", parse_mode="Markdown"
        )
        return
    new_name = " ".join(context.args)
    if len(new_name) > 30:
        await update.message.reply_text("Name must be 30 characters or fewer.")
        return
    db_execute(
        "UPDATE users SET display_name = ? WHERE user_id = ?",
        (new_name, user_id),
        commit=True,
        db_name=db_name,
    )
    await update.message.reply_text(
        f"Your name has been updated to: *{new_name}*", parse_mode="Markdown"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = get_db_name(context)
    top_users = db_execute(
        "SELECT display_name, message_count FROM users "
        "ORDER BY message_count DESC LIMIT 10",
        fetchall=True,
        db_name=db_name,
    )
    if not top_users or top_users[0][1] == 0:
        await update.message.reply_text(
            "No messages sent yet! Be the first to start talking."
        )
        return
    text = "🏆 *Top Chatters Leaderboard* 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for index, (name, count) in enumerate(top_users, start=1):
        prefix = medals[index - 1] if index <= 3 else f"`{index}.`"
        text += f"{prefix} *{name}*: {count} messages\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def sync_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = get_db_name(context)
    media_records = db_execute(
        "SELECT sender_name, file_id, caption, timestamp FROM media_store ORDER BY timestamp ASC",
        fetchall=True,
        db_name=db_name,
    )
    if not media_records:
        await update.message.reply_text("No media has been shared in this chat yet.")
        return

    await update.message.reply_text(f"📦 Syncing {len(media_records)} media item(s)...")
    
    for sender_name, file_id, caption, timestamp in media_records:
        formatted_caption = f"From *{sender_name}* ({timestamp}):\n{caption}" if caption else f"From *{sender_name}* ({timestamp})"
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=file_id,
                caption=formatted_caption,
                parse_mode="Markdown",
            )
        except Exception:
            await update.message.reply_text(f"⚠️ Could not load media from *{sender_name}* (expired or deleted).")

async def list_cloned_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all cloned bots created through this system."""
    cloned_bots = db_execute(
        "SELECT bot_username, timestamp FROM cloned_bots ORDER BY timestamp DESC",
        fetchall=True,
        db_name="chat_bot.db"
    )
    if not cloned_bots:
        await update.message.reply_text("No cloned bots have been created yet.")
        return

    text = "🤖 *Deployed Cloned Bots* 🤖\n\n"
    for username, timestamp in cloned_bots:
        text += f"• @{username} (Created: {timestamp})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# --- CLONE COMMAND LOGIC ---
async def clone_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 *Bot Cloning Assistant* 🔄\n\n"
        "Want to run your own copy of this bot?\n"
        "1. Go to [@BotFather](https://t.me/BotFather) and create a new bot.\n"
        "2. Copy the **HTTP API Token** he gives you.\n"
        "3. Send me that token here.\n\n"
        "_Send /cancel to abort._",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    return CLONE_TOKEN

def run_bot_process(token):
    """Target function to run a cloned bot instance inside an isolated background process."""
    try:
        db_name = f"bot_{token.split(':')[0]}.db"
        init_db(db_name)

        cloned_app = ApplicationBuilder().token(token).build()
        cloned_app.bot_data["db_name"] = db_name

        cloned_app.add_handler(CommandHandler("start", start))
        cloned_app.add_handler(CommandHandler("help", help_command))
        cloned_app.add_handler(CommandHandler("setmyname", set_name))
        cloned_app.add_handler(CommandHandler("leaderboard", leaderboard))
        cloned_app.add_handler(CommandHandler("syncmedia", sync_media))
        cloned_app.add_handler(CommandHandler("clonedbot", list_cloned_bots))
        
        clone_handler_local = ConversationHandler(
            entry_points=[CommandHandler("clone", clone_start)],
            states={
                CLONE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_clone_token)]
            },
            fallbacks=[CommandHandler("cancel", cancel_clone)]
        )
        cloned_app.add_handler(clone_handler_local)
        cloned_app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO) & ~filters.COMMAND & filters.ChatType.PRIVATE,
                broadcast_message,
            )
        )

        cloned_app.run_polling()
    except Exception as e:
        logging.error(f"Cloned bot process error: {e}")

async def receive_clone_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_token = update.message.text.strip()
    
    if ":" not in new_token or len(new_token) < 20:
        await update.message.reply_text("❌ Invalid token format. Please send a valid BotFather token or type /cancel.")
        return CLONE_TOKEN

    await update.message.reply_text("⚙️ Verifying token and starting your new bot instance...")

    try:
        # Verify token and fetch bot username
        temp_bot = Bot(token=new_token)
        bot_info = await temp_bot.get_me()
        bot_username = bot_info.username

        # Save to database
        db_execute(
            "INSERT OR IGNORE INTO cloned_bots (owner_id, bot_token, bot_username) VALUES (?, ?, ?)",
            (update.effective_user.id, new_token, bot_username),
            commit=True,
            db_name="chat_bot.db"
        )

        # Start isolated process
        process = multiprocessing.Process(target=run_bot_process, args=(new_token,))
        process.daemon = True
        process.start()

        await update.message.reply_text(
            f"✅ Success! Your cloned bot is now running.\n"
            f"Search for it on Telegram: @{bot_username}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to start bot. Make sure your token is correct. Error: {e}")

    return ConversationHandler.END

async def cancel_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Clone process cancelled.")
    return ConversationHandler.END

# --- BROADCAST HANDLER ---
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_name = get_db_name(context)
    sender_id = update.effective_user.id
    sender_data = db_execute(
        "SELECT display_name FROM users WHERE user_id = ?",
        (sender_id,),
        fetchone=True,
        db_name=db_name,
    )
    if not sender_data:
        sender_name = f"User_{str(sender_id)[-4:]}"
        db_execute(
            "INSERT INTO users (user_id, display_name, message_count, is_active) "
            "VALUES (?, ?, 1, 1)",
            (sender_id, sender_name),
            commit=True,
            db_name=db_name,
        )
    else:
        sender_name = sender_data[0]
        db_execute(
            "UPDATE users SET message_count = message_count + 1, is_active = 1 "
            "WHERE user_id = ?",
            (sender_id,),
            commit=True,
            db_name=db_name,
        )
    active_users = db_execute(
        "SELECT user_id FROM users WHERE is_active = 1", 
        fetchall=True, 
        db_name=db_name
    )
    
    if update.message.text:
        formatted_msg = f"*{sender_name}*: {update.message.text}"
        for (recipient_id,) in active_users:
            if recipient_id != sender_id:
                try:
                    await context.bot.send_message(
                        chat_id=recipient_id,
                        text=formatted_msg,
                        parse_mode="Markdown",
                    )
                except Exception:
                    db_execute(
                        "UPDATE users SET is_active = 0 WHERE user_id = ?",
                        (recipient_id,),
                        commit=True,
                        db_name=db_name,
                    )
                    
    elif update.message.photo:
        photo_id = update.message.photo[-1].file_id
        caption_text = update.message.caption if update.message.caption else ""
        
        db_execute(
            "INSERT INTO media_store (sender_id, sender_name, file_id, caption) VALUES (?, ?, ?, ?)",
            (sender_id, sender_name, photo_id, caption_text),
            commit=True,
            db_name=db_name,
        )
        
        caption = (
            f"*{sender_name}*: {caption_text}"
            if caption_text
            else f"*{sender_name}*"
        )
        for (recipient_id,) in active_users:
            if recipient_id != sender_id:
                try:
                    await context.bot.send_photo(
                        chat_id=recipient_id,
                        photo=photo_id,
                        caption=caption,
                        parse_mode="Markdown",
                    )
                except Exception:
                    db_execute(
                        "UPDATE users SET is_active = 0 WHERE user_id = ?",
                        (recipient_id,),
                        commit=True,
                        db_name=db_name,
                    )

def main():
    # Required for safe multiprocessing across platforms
    multiprocessing.freeze_support()

    app = ApplicationBuilder().token(TOKEN).build()
    app.bot_data["db_name"] = "chat_bot.db"
    
    clone_handler = ConversationHandler(
        entry_points=[CommandHandler("clone", clone_start)],
        states={
            CLONE_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_clone_token)]
        },
        fallbacks=[CommandHandler("cancel", cancel_clone)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setmyname", set_name))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("syncmedia", sync_media))
    app.add_handler(CommandHandler("clonedbot", list_cloned_bots))
    app.add_handler(clone_handler)
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND & filters.ChatType.PRIVATE,
            broadcast_message,
        )
    )
    print("Main bot is running with your token...")
    app.run_polling()

if __name__ == "__main__":
    main()
