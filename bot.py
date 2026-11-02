
import os
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

ADMIN_ID = 1105772687
TOKEN = os.getenv("BOT_TOKEN")
DB = "users.db"

def setup_db():
    with sqlite3.connect(DB) as con:
        con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")

def save_user(uid):
    with sqlite3.connect(DB) as con:
        con.execute("INSERT OR IGNORE INTO users VALUES (?)", (uid,))

def get_users():
    with sqlite3.connect(DB) as con:
        return [r[0] for r in con.execute("SELECT id FROM users")]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    save_user(uid)
    await update.message.reply_text(
        "Welcome to Kaptaan Choudhary! 🏏\nSend your message here."
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        f"Total registered users: {len(get_users())}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data["broadcast_wait"] = True
    context.user_data.pop("reply_to", None)
    await update.message.reply_text(
        "Send the text, photo, video or document you want to broadcast."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    # Admin message handling
    if user.id == ADMIN_ID:
        if context.user_data.get("broadcast_wait"):
            context.user_data["broadcast_wait"] = False
            context.user_data["pending_broadcast"] = msg.message_id
            keyboard = [[
                InlineKeyboardButton("✅ Send to all", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
            ]]
            await msg.reply_text(
                f"Broadcast preview ready.\nRecipients: {len(get_users())}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        target = context.user_data.get("reply_to")
        if target:
            try:
                await context.bot.copy_message(
                    chat_id=target,
                    from_chat_id=ADMIN_ID,
                    message_id=msg.message_id
                )
                await msg.reply_text("✅ Reply sent.")
            except Exception as e:
                await msg.reply_text(f"Could not send: {e}")
            context.user_data.pop("reply_to", None)
            return

        await msg.reply_text(
            "Admin commands:\n/stats - User count\n/broadcast - Send to all\n/cancel - Cancel action"
        )
        return

    # Register and forward user message to admin
    save_user(user.id)
    name = user.full_name
    username = f"@{user.username}" if user.username else "No username"
    keyboard = [[InlineKeyboardButton(
        "↩️ Reply to user", callback_data=f"reply:{user.id}"
    )]]
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 NEW USER MESSAGE\n\nName: {name}\nUsername: {username}\nUser ID: {user.id}"
    )
    await context.bot.copy_message(
        chat_id=ADMIN_ID,
        from_chat_id=user.id,
        message_id=msg.message_id,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    if query.data.startswith("reply:"):
        target = int(query.data.split(":")[1])
        context.user_data["reply_to"] = target
        await query.message.reply_text(
            f"Now send the reply for user {target}."
        )

    elif query.data == "cancel_broadcast":
        context.user_data.pop("pending_broadcast", None)
        await query.edit_message_text("Broadcast cancelled.")

    elif query.data == "confirm_broadcast":
        message_id = context.user_data.pop("pending_broadcast", None)
        if not message_id:
            await query.edit_message_text("No pending broadcast.")
            return

        await query.edit_message_text("Broadcast started...")
        sent = failed = 0

        for uid in get_users():
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=ADMIN_ID,
                    message_id=message_id
                )
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)

        await context.bot.send_message(
            ADMIN_ID,
            f"📊 BROADCAST REPORT\n\n✅ Sent: {sent}\n❌ Failed: {failed}"
        )

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    webhook_secret = os.getenv("WEBHOOK_SECRET")
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT", "10000"))

    if not webhook_secret or not render_url:
        raise RuntimeError("Webhook environment variables are missing")

    setup_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("Kaptaan Choudhary Bot is running!")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=webhook_secret,
        webhook_url=f"{render_url}/{webhook_secret}",
        secret_token=webhook_secret
    )


if __name__ == "__main__":
    main()
