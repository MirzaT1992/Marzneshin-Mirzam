"""
Telegram Bot for User Self-Service

This module provides a Telegram bot interface for users to:
- Link their Telegram account to their proxy account
- View account status (traffic, expiry, limits)
- Get subscription links and QR codes
- Receive notifications

Admin features:
- Add/remove users
- View statistics
- Manage users via bot
"""

import logging
import io
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.orm import Session

from app.db import GetDB, get_db
from app.db.models import User
from app.config.env import TELEGRAM_API_TOKEN, TELEGRAM_ADMIN_ID
from app.utils.share import generate_subscription
from app.db import crud

logger = logging.getLogger(__name__)


class LinkAccountState(StatesGroup):
    """States for linking Telegram account to user"""
    waiting_for_username = State()


def format_bytes(bytes_value: int) -> str:
    """Format bytes to human-readable format"""
    if bytes_value is None:
        return "Unlimited"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime to readable string"""
    if dt is None:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_user_by_telegram_id(db: Session, telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID"""
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def create_main_keyboard() -> InlineKeyboardMarkup:
    """Create main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(text="📊 Status", callback_data="status"),
            InlineKeyboardButton(text="🔗 Config", callback_data="config"),
        ],
        [
            InlineKeyboardButton(text="📱 QR Code", callback_data="qr"),
            InlineKeyboardButton(text="ℹ️ Help", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_config_format_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for config format selection"""
    keyboard = [
        [
            InlineKeyboardButton(text="V2Ray", callback_data="config_v2ray"),
            InlineKeyboardButton(text="Clash", callback_data="config_clash"),
        ],
        [
            InlineKeyboardButton(text="Clash Meta", callback_data="config_clash_meta"),
            InlineKeyboardButton(text="Sing-Box", callback_data="config_singbox"),
        ],
        [InlineKeyboardButton(text="« Back", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command"""
    telegram_id = message.from_user.id

    with GetDB() as db:
        user = get_user_by_telegram_id(db, telegram_id)

    if user:
        await message.answer(
            f"👋 Welcome back, <b>{user.username}</b>!\n\n"
            f"Your account is linked. Use the menu below to manage your account.",
            reply_markup=create_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "👋 Welcome to Marzneshin Bot!\n\n"
            "To use this bot, you need to link your Telegram account to your proxy account.\n\n"
            "Use /link command with your username:\n"
            "<code>/link your_username</code>",
            parse_mode="HTML"
        )


async def cmd_link(message: Message, state: FSMContext):
    """Handle /link command to link Telegram account"""
    telegram_id = message.from_user.id

    # Extract username from command
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Please provide your username:\n"
            "<code>/link your_username</code>",
            parse_mode="HTML"
        )
        return

    username = args[1].strip()

    with GetDB() as db:
        # Check if already linked
        existing_user = get_user_by_telegram_id(db, telegram_id)
        if existing_user:
            await message.answer(
                f"⚠️ Your Telegram account is already linked to: <b>{existing_user.username}</b>\n\n"
                f"To relink, please contact an administrator.",
                parse_mode="HTML"
            )
            return

        # Find user by username
        user = crud.get_user(db, username)
        if not user:
            await message.answer(
                f"❌ User <b>{username}</b> not found.\n\n"
                f"Please check your username and try again.",
                parse_mode="HTML"
            )
            return

        # Check if user already has a telegram_id
        if user.telegram_id:
            await message.answer(
                f"❌ This account is already linked to another Telegram account.\n\n"
                f"Please contact an administrator.",
                parse_mode="HTML"
            )
            return

        # Link the account
        user.telegram_id = telegram_id
        db.commit()

        await message.answer(
            f"✅ Successfully linked!\n\n"
            f"Your Telegram account is now linked to: <b>{username}</b>\n\n"
            f"Use the menu below to manage your account.",
            reply_markup=create_main_keyboard(),
            parse_mode="HTML"
        )
        logger.info(f"Telegram account {telegram_id} linked to user {username}")


async def cmd_unlink(message: Message):
    """Handle /unlink command"""
    telegram_id = message.from_user.id

    with GetDB() as db:
        user = get_user_by_telegram_id(db, telegram_id)
        if not user:
            await message.answer("❌ Your Telegram account is not linked to any user.")
            return

        username = user.username
        user.telegram_id = None
        db.commit()

        await message.answer(
            f"✅ Successfully unlinked from <b>{username}</b>!",
            parse_mode="HTML"
        )
        logger.info(f"Telegram account {telegram_id} unlinked from user {username}")


async def cmd_status(message: Message):
    """Handle /status command"""
    telegram_id = message.from_user.id

    with GetDB() as db:
        user = get_user_by_telegram_id(db, telegram_id)
        if not user:
            await message.answer(
                "❌ Your Telegram account is not linked.\n\n"
                "Use /link to link your account."
            )
            return

        # Calculate remaining data
        if user.data_limit:
            used_percentage = (user.used_traffic / user.data_limit) * 100
            remaining = user.data_limit - user.used_traffic
        else:
            used_percentage = 0
            remaining = None

        # Build status message
        status_text = f"📊 <b>Account Status</b>\n\n"
        status_text += f"👤 Username: <b>{user.username}</b>\n"
        status_text += f"🔑 Status: {'✅ Active' if user.is_active else '❌ Inactive'}\n"
        status_text += f"📅 Created: {format_datetime(user.created_at)}\n\n"

        status_text += f"📈 <b>Traffic Usage</b>\n"
        status_text += f"📤 Used: {format_bytes(user.used_traffic)}\n"
        status_text += f"📊 Limit: {format_bytes(user.data_limit)}\n"
        if user.data_limit:
            status_text += f"📉 Remaining: {format_bytes(remaining)}\n"
            status_text += f"📈 Usage: {used_percentage:.1f}%\n"
        status_text += f"\n"

        status_text += f"⏰ <b>Expiry</b>\n"
        status_text += f"📅 Expire Date: {format_datetime(user.expire_date)}\n"
        status_text += f"⏳ Status: {'❌ Expired' if user.expired else '✅ Active'}\n"

        await message.answer(status_text, parse_mode="HTML", reply_markup=create_main_keyboard())


async def cmd_config(message: Message):
    """Handle /config command"""
    telegram_id = message.from_user.id

    with GetDB() as db:
        user = get_user_by_telegram_id(db, telegram_id)
        if not user:
            await message.answer(
                "❌ Your Telegram account is not linked.\n\n"
                "Use /link to link your account."
            )
            return

    await message.answer(
        "📱 <b>Select Config Format</b>\n\n"
        "Choose the format for your subscription link:",
        reply_markup=create_config_format_keyboard(),
        parse_mode="HTML"
    )


async def cmd_help(message: Message):
    """Handle /help command"""
    help_text = (
        "🤖 <b>Marzneshin Bot Help</b>\n\n"
        "<b>User Commands:</b>\n"
        "/start - Start the bot\n"
        "/link [username] - Link your Telegram account\n"
        "/unlink - Unlink your account\n"
        "/status - View your account status\n"
        "/config - Get your subscription link\n"
        "/qr - Get QR code\n"
        "/help - Show this help message\n\n"
        "<b>Admin Commands:</b>\n"
        "/stats - View system statistics\n"
        "/broadcast - Send message to all users\n\n"
        "💡 <b>Tip:</b> Use the inline buttons for easier navigation!"
    )

    await message.answer(help_text, parse_mode="HTML")


# Admin commands
async def cmd_stats(message: Message):
    """Handle /stats command (admin only)"""
    telegram_id = message.from_user.id

    # Check if user is admin
    if TELEGRAM_ADMIN_ID and telegram_id not in TELEGRAM_ADMIN_ID:
        await message.answer("❌ This command is only available to administrators.")
        return

    with GetDB() as db:
        total_users = db.query(User).filter(User.removed == False).count()
        active_users = db.query(User).filter(
            User.removed == False,
            User.enabled == True,
            User.activated == True
        ).count()

        stats_text = (
            f"📊 <b>System Statistics</b>\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Active Users: {active_users}\n"
            f"❌ Inactive Users: {total_users - active_users}\n"
        )

        await message.answer(stats_text, parse_mode="HTML")


async def cmd_broadcast(message: Message):
    """Handle /broadcast command (admin only)"""
    telegram_id = message.from_user.id

    # Check if user is admin
    if TELEGRAM_ADMIN_ID and telegram_id not in TELEGRAM_ADMIN_ID:
        await message.answer("❌ This command is only available to administrators.")
        return

    # Get message text after command
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Please provide a message to broadcast:\n"
            "<code>/broadcast Your message here</code>",
            parse_mode="HTML"
        )
        return

    broadcast_text = args[1]

    with GetDB() as db:
        users_with_telegram = db.query(User).filter(
            User.telegram_id.isnot(None),
            User.removed == False
        ).all()

        sent_count = 0
        failed_count = 0

        for user in users_with_telegram:
            try:
                await message.bot.send_message(
                    user.telegram_id,
                    f"📢 <b>Broadcast Message</b>\n\n{broadcast_text}",
                    parse_mode="HTML"
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send broadcast to {user.username}: {e}")
                failed_count += 1

        await message.answer(
            f"✅ Broadcast sent!\n\n"
            f"📤 Sent: {sent_count}\n"
            f"❌ Failed: {failed_count}",
            parse_mode="HTML"
        )


def setup_handlers(dp: Dispatcher):
    """Setup all bot handlers"""
    # User commands
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_link, Command("link"))
    dp.message.register(cmd_unlink, Command("unlink"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_config, Command("config"))
    dp.message.register(cmd_help, Command("help"))

    # Admin commands
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_broadcast, Command("broadcast"))

    logger.info("Telegram bot handlers registered")


async def start_bot():
    """Start the Telegram bot"""
    if not TELEGRAM_API_TOKEN:
        logger.warning("Telegram bot token not configured, bot will not start")
        return None

    try:
        bot = Bot(token=TELEGRAM_API_TOKEN)
        dp = Dispatcher(storage=MemoryStorage())

        setup_handlers(dp)

        # Start polling
        await dp.start_polling(bot)

        logger.info("Telegram bot started successfully")
        return dp

    except Exception as e:
        logger.error(f"Failed to start Telegram bot: {e}")
        return None
