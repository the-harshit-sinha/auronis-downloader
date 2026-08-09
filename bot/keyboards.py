"""
Inline keyboard layouts.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📥 Download", callback_data="menu:download"),
                InlineKeyboardButton("📋 Queue", callback_data="menu:queue"),
            ],
            [
                InlineKeyboardButton("📊 Stats", callback_data="menu:stats"),
                InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
            ],
            [InlineKeyboardButton("🆘 Help", callback_data="menu:help")],
        ]
    )


def queue_view(has_pending: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🔄 Refresh", callback_data="queue:refresh")]]
    if has_pending:
        rows.append([InlineKeyboardButton("🛑 Cancel Queue", callback_data="queue:cancel")])
    return InlineKeyboardMarkup(rows)


def confirm_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, cancel", callback_data="cancel:confirm"),
                InlineKeyboardButton("❌ No", callback_data="cancel:abort"),
            ]
        ]
    )
