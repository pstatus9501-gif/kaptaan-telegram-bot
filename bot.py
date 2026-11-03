
import os
import asyncio
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

ADMIN_ID = 1105772687
TOKEN = os.getenv("BOT_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }


# ---------------- USER DATABASE ----------------

async def save_user(uid):
    url = f"{SUPABASE_URL}/rest/v1/users"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            params={"on_conflict": "id"},
            headers=supabase_headers(),
            json={"id": uid}
        )
        response.raise_for_status()


async def get_users():
    url = f"{SUPABASE_URL}/rest/v1/users"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            url,
            params={"select": "id"},
            headers=supabase_headers()
        )
        response.raise_for_status()
        return [row["id"] for row in response.json()]


# ---------------- TOSS / MATCH DATABASE ----------------

async def save_auto_message(key, chat_id, message_id):
    url = f"{SUPABASE_URL}/rest/v1/bot_messages"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            params={"on_conflict": "key"},
            headers=supabase_headers(),
            json={
                "key": key,
                "chat_id": chat_id,
                "message_id": message_id
            }
        )
        response.raise_for_status()


async def get_auto_message(key):
    url = f"{SUPABASE_URL}/rest/v1/bot_messages"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            url,
            params={
                "select": "chat_id,message_id",
                "key": f"eq.{key}"
            },
            headers=supabase_headers()
        )
        response.raise_for_status()

        data = response.json()
        return data[0] if data else None


async def delete_auto_message(key):
    url = f"{SUPABASE_URL}/rest/v1/bot_messages"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.delete(
            url,
            params={"key": f"eq.{key}"},
            headers=supabase_headers()
        )
        response.raise_for_status()


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save_user(uid)

    await update.message.reply_text(
        "Welcome to Kaptaan Choudhary! 🏏\nSend your message here."
    )


# ---------------- STATS ----------------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = await get_users()

    await update.message.reply_text(
        f"Total registered users: {len(users)}"
    )


# ---------------- BROADCAST ----------------

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.pop("reply_to", None)
    context.user_data.pop("set_message_for", None)
    context.user_data["broadcast_wait"] = True

    await update.message.reply_text(
        "Send the text, photo, video or document you want to broadcast."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
    await update.message.reply_text("Cancelled.")


# ---------------- SET TOSS / MATCH ----------------

async def settoss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
    context.user_data["set_message_for"] = "toss"

    await update.message.reply_text(
        "🏏 Send your TOSS message now.\n"
        "Text, photo, video or document supported."
    )


async def setmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
    context.user_data["set_message_for"] = "match"

    await update.message.reply_text(
        "🏆 Send your MATCH WINNER message now.\n"
        "Text, photo, video or document supported."
    )


# ---------------- CANCEL TOSS / MATCH ----------------

async def canceltoss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await delete_auto_message("toss")
        await update.message.reply_text(
            "✅ Toss auto-reply successfully deactivated."
        )
    except Exception as e:
        await update.message.reply_text(
            f"Could not cancel Toss: {e}"
        )


async def cancelmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await delete_auto_message("match")
        await update.message.reply_text(
            "✅ Match auto-reply successfully deactivated."
        )
    except Exception as e:
        await update.message.reply_text(
            f"Could not cancel Match: {e}"
        )


# ---------------- HANDLE MESSAGES ----------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not msg or not user:
        return

    # ADMIN MESSAGES
    if user.id == ADMIN_ID:

        # Save Toss / Match message
        setting = context.user_data.get("set_message_for")

        if setting:
            try:
                await save_auto_message(
                    setting,
                    msg.chat_id,
                    msg.message_id
                )

                context.user_data.pop("set_message_for", None)

                await msg.reply_text(
                    f"✅ {setting.upper()} message saved successfully!\n"
                    "Users can now request it automatically."
                )

            except Exception as e:
                await msg.reply_text(
                    f"❌ Message could not be saved: {e}"
                )

            return

        # Broadcast preview
        if context.user_data.get("broadcast_wait"):
            context.user_data["broadcast_wait"] = False
            context.user_data["pending_broadcast"] = msg.message_id

            users = await get_users()

            keyboard = [[
                InlineKeyboardButton(
                    "✅ Send to all",
                    callback_data="confirm_broadcast"
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="cancel_broadcast"
                )
            ]]

            await msg.reply_text(
                f"Broadcast preview ready.\nRecipients: {len(users)}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Admin reply
        target = context.user_data.get("reply_to")

        if target:
            try:
                await context.bot.copy_message(
                    chat_id=target,
                    from_chat_id=msg.chat_id,
                    message_id=msg.message_id
                )
                await msg.reply_text("✅ Reply sent.")

            except Exception as e:
                await msg.reply_text(f"Could not send: {e}")

            context.user_data.pop("reply_to", None)
            return

        await msg.reply_text(
            "Admin commands:\n"
            "/stats - User count\n"
            "/broadcast - Send to all\n"
            "/settoss - Set Toss message\n"
            "/setmatch - Set Match message\n"
            "/canceltoss - Cancel Toss\n"
            "/cancelmatch - Cancel Match\n"
            "/cancel - Cancel current action"
        )
        return

    # REGISTER USER
    await save_user(user.id)

    # AUTOMATIC TOSS / MATCH REPLY
    request = msg.text.strip().lower() if msg.text else ""

    if request in ("toss", "match"):

        saved = await get_auto_message(request)

        if not saved:
            await msg.reply_text(
                f"Sorry! {request.capitalize()} prediction "
                "is currently unavailable."
            )
            return

        try:
            await context.bot.copy_message(
                chat_id=user.id,
                from_chat_id=saved["chat_id"],
                message_id=saved["message_id"]
            )
        except Exception:
            await msg.reply_text(
                "Sorry! Message could not be delivered. Please try again."
            )

        return

    # FORWARD OTHER USER MESSAGES TO ADMIN
    name = user.full_name
    username = f"@{user.username}" if user.username else "No username"

    keyboard = [[
        InlineKeyboardButton(
            "↩️ Reply to user",
            callback_data=f"reply:{user.id}"
        )
    ]]

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📩 NEW USER MESSAGE\n\n"
            f"Name: {name}\n"
            f"Username: {username}\n"
            f"User ID: {user.id}"
        )
    )

    await context.bot.copy_message(
        chat_id=ADMIN_ID,
        from_chat_id=user.id,
        message_id=msg.message_id,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------------- BUTTONS ----------------

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

        users = await get_users()
        sent = failed = 0

        for uid in users:
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
            f"📊 BROADCAST REPORT\n\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}"
        )


# ---------------- MAIN ----------------

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    print("SUPABASE_URL loaded:", bool(SUPABASE_URL))
    print("SUPABASE_KEY loaded:", bool(SUPABASE_KEY))

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL or SUPABASE_KEY is missing")

    webhook_secret = os.getenv("WEBHOOK_SECRET")
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT", "10000"))

    if not webhook_secret or not render_url:
        raise RuntimeError("Webhook environment variables are missing")

    app = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CommandHandler("settoss", settoss))
    app.add_handler(CommandHandler("setmatch", setmatch))
    app.add_handler(CommandHandler("canceltoss", canceltoss))
    app.add_handler(CommandHandler("cancelmatch", cancelmatch))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
    )

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
