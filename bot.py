
import os
import asyncio
import uuid
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

ADMIN_ID = 1105772687
TOKEN = os.getenv("BOT_TOKEN")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def supabase_headers(prefer="resolution=merge-duplicates,return=minimal"):
    return {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": prefer
    }


# ---------------- DATABASE HELPERS ----------------

async def db_request(method, table, params=None, data=None, prefer=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method,
            url,
            params=params,
            headers=supabase_headers(
                prefer or "resolution=merge-duplicates,return=minimal"
            ),
            json=data
        )
        response.raise_for_status()

        if response.text:
            return response.json()

        return None


# ---------------- USER DATABASE ----------------

async def save_user(uid):
    await db_request(
        "POST", "users",
        params={"on_conflict": "id"},
        data={"id": uid}
    )


async def get_users():
    users = []
    offset = 0
    batch_size = 1000

    while True:
        data = await db_request(
            "GET", "users",
            params={
                "select": "id",
                "order": "id.asc",
                "limit": batch_size,
                "offset": offset
            }
        )

        if not data:
            break

        users.extend(row["id"] for row in data)
        offset += batch_size

        if len(data) < batch_size:
            break

    return users


# ---------------- TOSS / MATCH DATABASE ----------------

async def save_auto_message(key, chat_id, message_id):
    await db_request(
        "POST", "bot_messages",
        params={"on_conflict": "key"},
        data={
            "key": key,
            "chat_id": chat_id,
            "message_id": message_id
        }
    )


async def get_auto_message(key):
    data = await db_request(
        "GET", "bot_messages",
        params={
            "select": "chat_id,message_id",
            "key": f"eq.{key}"
        }
    )
    return data[0] if data else None


async def delete_auto_message(key):
    await db_request(
        "DELETE", "bot_messages",
        params={"key": f"eq.{key}"}
    )


# ---------------- SETTINGS DATABASE ----------------

async def set_setting(key, value):
    await db_request(
        "POST", "bot_settings",
        params={"on_conflict": "key"},
        data={"key": key, "value": value}
    )


async def get_setting(key):
    data = await db_request(
        "GET", "bot_settings",
        params={
            "select": "value",
            "key": f"eq.{key}"
        }
    )
    return data[0]["value"] if data else None


async def delete_setting(key):
    await db_request(
        "DELETE", "bot_settings",
        params={"key": f"eq.{key}"}
    )


# ---------------- MATCH APPROVAL DATABASE ----------------

async def is_approved(uid, cycle_id):
    data = await db_request(
        "GET", "user_approvals",
        params={
            "select": "user_id",
            "user_id": f"eq.{uid}",
            "cycle_id": f"eq.{cycle_id}"
        }
    )
    return bool(data)


async def save_approval(uid, cycle_id):
    await db_request(
        "POST", "user_approvals",
        params={"on_conflict": "user_id,cycle_id"},
        data={
            "user_id": uid,
            "cycle_id": cycle_id
        }
    )


async def save_session(uid, cycle_id, request_type):
    await db_request(
        "POST", "verification_sessions",
        params={"on_conflict": "user_id"},
        data={
            "user_id": uid,
            "cycle_id": cycle_id,
            "request_type": request_type
        }
    )


async def get_session(uid):
    data = await db_request(
        "GET", "verification_sessions",
        params={
            "select": "user_id,cycle_id,request_type",
            "user_id": f"eq.{uid}"
        }
    )
    return data[0] if data else None


async def delete_session(uid):
    await db_request(
        "DELETE", "verification_sessions",
        params={"user_id": f"eq.{uid}"}
    )


async def get_pending_request(uid, cycle_id):
    data = await db_request(
        "GET", "verification_requests",
        params={
            "select": "id",
            "user_id": f"eq.{uid}",
            "cycle_id": f"eq.{cycle_id}",
            "status": "eq.pending"
        }
    )
    return data[0] if data else None


async def create_verification_request(uid, cycle_id, message_id):
    data = await db_request(
        "POST", "verification_requests",
        data={
            "user_id": uid,
            "cycle_id": cycle_id,
            "message_id": message_id,
            "status": "pending"
        },
        prefer="return=representation"
    )
    return data[0]["id"]


async def get_verification_request(request_id):
    data = await db_request(
        "GET", "verification_requests",
        params={
            "select": "id,user_id,cycle_id,message_id,status",
            "id": f"eq.{request_id}"
        }
    )
    return data[0] if data else None


async def update_request_status(request_id, status):
    await db_request(
        "PATCH", "verification_requests",
        params={"id": f"eq.{request_id}"},
        data={"status": status}
    )


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save_user(uid)

    await update.message.reply_text(
        "Welcome to Kaptaan Choudhary! 🏏\n"
        "Send Toss or Match to request the latest update."
    )


# ---------------- NEW MATCH ----------------

async def newmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        cycle_id = str(uuid.uuid4())
        await set_setting("current_cycle", cycle_id)

        await update.message.reply_text(
            "🆕 NEW MATCH CYCLE STARTED!\n\n"
            "✅ Previous approvals are now expired.\n"
            "🔒 All users must verify again.\n\n"
            "Now use /setreel to add the new Instagram reel link."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ---------------- INSTAGRAM REEL COMMANDS ----------------

async def setreel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
    context.user_data["set_reel"] = True

    await update.message.reply_text(
        "📸 Send the Instagram reel link now.\n\n"
        "Example: https://www.instagram.com/reel/XXXXXXXX/"
    )


async def showreel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    link = await get_setting("reel_url")

    await update.message.reply_text(
        f"Current Instagram reel:\n{link}" if link
        else "❌ No Instagram reel link is set."
    )


async def removereel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await delete_setting("reel_url")
        await update.message.reply_text(
            "✅ Instagram reel link removed."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        data = await db_request(
            "GET", "verification_requests",
            params={
                "select": "id,user_id,cycle_id,created_at",
                "status": "eq.pending",
                "order": "created_at.asc",
                "limit": "30"
            }
        )

        if not data:
            await update.message.reply_text(
                "✅ No pending verification requests."
            )
            return

        lines = ["📋 PENDING VERIFICATIONS:\n"]

        for item in data:
            lines.append(
                f"Request #{item['id']} | User: {item['user_id']}"
            )

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ---------------- STATS ----------------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = await get_users()

    cycle = await get_setting("current_cycle")

    approved_count = 0

    if cycle:
        data = await db_request(
            "GET", "user_approvals",
            params={
                "select": "user_id",
                "cycle_id": f"eq.{cycle}"
            }
        )
        approved_count = len(data or [])

    await update.message.reply_text(
        f"📊 KAPTAAN CHOUDHARY STATS\n\n"
        f"Total users: {len(users)}\n"
        f"Current match approvals: {approved_count}"
    )


# ---------------- BROADCAST ----------------

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
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
        "🏏 Send your TOSS message now."
    )


async def setmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()
    context.user_data["set_message_for"] = "match"

    await update.message.reply_text(
        "🏆 Send your MATCH WINNER message now."
    )


async def canceltoss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await delete_auto_message("toss")
        await update.message.reply_text(
            "✅ Toss auto-reply deactivated."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cancelmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await delete_auto_message("match")
        await update.message.reply_text(
            "✅ Match auto-reply deactivated."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ---------------- USER TOSS / MATCH REQUEST ----------------

async def request_prediction(update, context, request_type):
    user = update.effective_user
    msg = update.effective_message

    await save_user(user.id)

    cycle = await get_setting("current_cycle")
    reel = await get_setting("reel_url")

    if not cycle:
        await msg.reply_text(
            "Sorry! New match verification is not active yet."
        )
        return

    if not reel:
        await msg.reply_text(
            "Instagram verification link is currently unavailable."
        )
        return

    if await is_approved(user.id, cycle):
        saved = await get_auto_message(request_type)

        if not saved:
            await msg.reply_text(
                f"{request_type.capitalize()} message is currently unavailable."
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
                "Message could not be delivered. Please try again."
            )

        return

    existing = await get_pending_request(user.id, cycle)

    if existing:
        await msg.reply_text(
            "⏳ Your screenshot is already waiting for admin approval."
        )
        return

    await save_session(user.id, cycle, request_type)

    await msg.reply_text(
        "🔒 INSTAGRAM LIKE VERIFICATION\n\n"
        "1. Open our Instagram reel.\n"
        "2. Like the reel.\n"
        "3. Take a screenshot showing your like.\n"
        "4. Send that screenshot here.\n\n"
        f"📸 Reel link:\n{reel}\n\n"
        "Your Toss and Match access will unlock after admin approval."
    )


# ---------------- SCREENSHOT SUBMISSION ----------------

async def submit_screenshot(update, context):
    msg = update.effective_message
    user = update.effective_user

    cycle = await get_setting("current_cycle")
    session = await get_session(user.id)

    if not session or not cycle:
        return False

    if session["cycle_id"] != cycle:
        await delete_session(user.id)
        await msg.reply_text(
            "This verification belongs to an old match. "
            "Please request Toss or Match again."
        )
        return True

    existing = await get_pending_request(user.id, cycle)

    if existing:
        await msg.reply_text(
            "⏳ Your screenshot is already waiting for approval."
        )
        return True

    is_image = bool(msg.photo)

    if msg.document and msg.document.mime_type:
        is_image = msg.document.mime_type.startswith("image/")

    if not is_image:
        await msg.reply_text(
            "Please send a screenshot as an image."
        )
        return True

    try:
        request_id = await create_verification_request(
            user.id,
            cycle,
            msg.message_id
        )

        keyboard = [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approve:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{request_id}"
            )
        ]]

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "📸 NEW INSTAGRAM VERIFICATION\n\n"
                f"Request ID: {request_id}\n"
                f"Name: {user.full_name}\n"
                f"Username: @{user.username if user.username else 'No username'}\n"
                f"User ID: {user.id}\n"
                f"Requested: {session['request_type'].upper()}\n\n"
                "Check the screenshot below."
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        await context.bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=user.id,
            message_id=msg.message_id
        )

        await msg.reply_text(
            "✅ Screenshot submitted successfully!\n"
            "Please wait for admin approval."
        )

    except Exception as e:
        await msg.reply_text(
            f"❌ Screenshot submission failed: {e}"
        )

    return True


# ---------------- HANDLE MESSAGES ----------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not msg or not user:
        return

    # ADMIN
    if user.id == ADMIN_ID:

        if context.user_data.get("set_reel"):
            link = msg.text.strip() if msg.text else ""

            if not (
                link.startswith("https://www.instagram.com/")
                or link.startswith("https://instagram.com/")
            ):
                await msg.reply_text(
                    "❌ Please send a valid Instagram URL."
                )
                return

            try:
                await set_setting("reel_url", link)
                context.user_data.pop("set_reel", None)

                await msg.reply_text(
                    "✅ Instagram reel link saved successfully!"
                )
            except Exception as e:
                await msg.reply_text(f"❌ Error: {e}")

            return

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
                    f"✅ {setting.upper()} message saved successfully!"
                )
            except Exception as e:
                await msg.reply_text(f"❌ Error: {e}")

            return

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
            "/newmatch - Start new match\n"
            "/setreel - Set Instagram reel\n"
            "/showreel - Show reel link\n"
            "/removereel - Remove reel link\n"
            "/pending - Pending screenshots\n"
            "/stats - User and approval count\n"
            "/broadcast - Send to all\n"
            "/settoss - Set Toss message\n"
            "/setmatch - Set Match message\n"
            "/canceltoss - Cancel Toss\n"
            "/cancelmatch - Cancel Match\n"
            "/cancel - Cancel current action"
        )
        return

    # USER
    await save_user(user.id)

    # Check screenshot submission
    if msg.photo or msg.document:
        handled = await submit_screenshot(update, context)
        if handled:
            return

    request = msg.text.strip().lower() if msg.text else ""

    if request in ("toss", "match"):
        await request_prediction(update, context, request)
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

# ---------------- BATCH BROADCAST SENDER ----------------

async def send_broadcast(context, message_id, users):
    sent = 0
    failed = 0
    total = len(users)

    for index, uid in enumerate(users, start=1):
        while True:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=ADMIN_ID,
                    message_id=message_id
                )
                sent += 1
                break

            except RetryAfter as e:
                wait_time = e.retry_after
                if hasattr(wait_time, "total_seconds"):
                    wait_time = wait_time.total_seconds()
                await asyncio.sleep(float(wait_time) + 1)

            except Exception:
                failed += 1
                break

        await asyncio.sleep(0.05)

        if index % 100 == 0:
            await asyncio.sleep(2)

    await context.bot.send_message(
        ADMIN_ID,
        f"📊 BROADCAST REPORT\n\n"
        f"👥 Total Users: {total}\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )
    
# ---------------- BUTTONS ----------------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    data = query.data

    if data.startswith("reply:"):
        target = int(data.split(":")[1])
        context.user_data["reply_to"] = target

        await query.message.reply_text(
            f"Now send the reply for user {target}."
        )
        return

    if data.startswith("approve:") or data.startswith("reject:"):
        action, request_id = data.split(":")
        request_id = int(request_id)

        try:
            request = await get_verification_request(request_id)

            if not request or request["status"] != "pending":
                await query.edit_message_text(
                    "This verification request is no longer pending."
                )
                return

            current_cycle = await get_setting("current_cycle")

            if request["cycle_id"] != current_cycle:
                await update_request_status(request_id, "expired")
                await query.edit_message_text(
                    "⚠️ This request belongs to an old match. Approval expired."
                )
                return

            uid = request["user_id"]

            if action == "approve":
                await save_approval(uid, current_cycle)
                await delete_session(uid)
                await update_request_status(request_id, "approved")

                await context.bot.send_message(
                    chat_id=uid,
                    text=(
                        "✅ INSTAGRAM VERIFICATION APPROVED!\n\n"
                        "Your Toss and Match access is now unlocked "
                        "for the current match. 🏏"
                    )
                )

                await query.edit_message_text(
                    f"✅ APPROVED\nRequest: {request_id}\nUser: {uid}"
                )

            else:
                await update_request_status(request_id, "rejected")

                await context.bot.send_message(
                    chat_id=uid,
                    text=(
                        "❌ Your Instagram screenshot was rejected.\n\n"
                        "Please send a clear screenshot showing that "
                        "you liked the reel."
                    )
                )

                await query.edit_message_text(
                    f"❌ REJECTED\nRequest: {request_id}\nUser: {uid}"
                )

        except Exception as e:
            await query.message.reply_text(
                f"❌ Approval action failed: {e}"
            )

        return

    if data == "cancel_broadcast":
        context.user_data.pop("pending_broadcast", None)
        await query.edit_message_text("Broadcast cancelled.")
        return

    if data == "confirm_broadcast":
        message_id = context.user_data.pop("pending_broadcast", None)

        if not message_id:
            await query.edit_message_text("No pending broadcast.")
            return

        await query.edit_message_text("🚀 Broadcast started...")

        try:
            users = await get_users()

            await send_broadcast(
                context,
                message_id,
                users
            )

        except Exception as e:
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ Broadcast error: {e}"
            )

        return


# ---------------- MAIN ----------------

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

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

    app.add_handler(CommandHandler("newmatch", newmatch))
    app.add_handler(CommandHandler("setreel", setreel))
    app.add_handler(CommandHandler("showreel", showreel))
    app.add_handler(CommandHandler("removereel", removereel))
    app.add_handler(CommandHandler("pending", pending))

    app.add_handler(CommandHandler("settoss", settoss))
    app.add_handler(CommandHandler("setmatch", setmatch))
    app.add_handler(CommandHandler("canceltoss", canceltoss))
    app.add_handler(CommandHandler("cancelmatch", cancelmatch))

    app.add_handler(CallbackQueryHandler(buttons))

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_message
        )
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
