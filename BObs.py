import os
import json
import logging
import datetime
import threading
import asyncio
import re
from collections import deque
from datetime import timezone, timedelta

import aiohttp
import discord
from groq import Groq, RateLimitError, APIStatusError
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask

load_dotenv()  # Load values from .env into environment variables

# ---------------------------------------------------------
# Logging: important for 24/7 runs to see where the bot fails
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("bobbot")

# ---------------------------------------------------------
# Theme colors — keeps every embed in the bot visually consistent
# ---------------------------------------------------------
class Theme:
    # A slightly richer, more "premium" palette than plain Discord defaults —
    # deeper saturation, better contrast against the dark theme.
    PRIMARY = discord.Color.from_rgb(124, 77, 255)      # rich indigo/violet
    SUCCESS = discord.Color.from_rgb(46, 213, 148)       # emerald
    DANGER = discord.Color.from_rgb(255, 71, 87)         # coral red
    WARNING = discord.Color.from_rgb(255, 177, 66)       # amber
    INFO = discord.Color.from_rgb(64, 156, 255)          # sky blue
    TICKET = discord.Color.from_rgb(0, 200, 150)         # teal-green
    SCRIPTHUB = discord.Color.from_rgb(168, 85, 247)     # electric purple
    ROLIMONS = discord.Color.from_rgb(56, 132, 255)      # roblox blue

    # Small "eyebrow" glyphs used to open a divider line with a bit of flair
    DIVIDER = "┈┈┈┈┈┈┈┈┈┈┈❖┈┈┈┈┈┈┈┈┈┈┈"
    BAR = "▎"  # thin accent bar prefixed to key lines for a "card" feel

    # Rotating accent colors used for Rules language sections when no
    # custom color is given.
    RULES_PALETTE = [
        discord.Color.from_rgb(255, 82, 82),
        discord.Color.from_rgb(66, 133, 244),
        discord.Color.from_rgb(52, 199, 123),
        discord.Color.from_rgb(255, 170, 51),
        discord.Color.from_rgb(178, 102, 255),
        discord.Color.from_rgb(45, 212, 191),
    ]


# ---------------------------------------------------------
# Custom Emoji (Application Emojis)
# ---------------------------------------------------------
CUSTOM_EMOJI_NAMES = {
    "success": "spbluetick",
    "check": "bluecheckmark",
    "verified": "verifiedids",
    "not_verified": "nonverifiedids",
    "certified": "certified",
    "info": "info",
    "lock": "lock",
    "star": "starids",
    "star_shiny": "bluestarshiny",
    "star_outline": "starblue",
    "thumbsup": "bluethumbsup",
    "heart": "blueheart",
    "heart_outline": "bluedrawingheart",
    "arrow": "darkbluearrow",
    "staff": "bluestaffbadge",
    "moderator": "moderator",
    "blue_moderator": "bluemoderator",
    "mod_shield": "modshieldicon",
    "ticket": "ticketicon",
    "shield": "shield",
    "link": "link",
    "web": "webicon",
    "discord_logo": "discordlogo",
    "legit": "legit",
    "warning": "exclamation",
    "error": "xoflash",
    "glowing_dot": "glowingdotblue",
    "planet": "blueplanet",
    "lines": "lines",
    "gift": "giftingpatron",
    "language": "blueplanet",

    "fun_clap": "pepeclap",
    "fun_love": "pepeheart",
    "fun_nervous": "pepenervous",
    "fun_wow": "pepewow",
    "fun_perfect": "pepeperfect",
    "fun_cry": "crying",
    "fun_ohno": "joobiohno",
    "fun_huh": "joobihuh",
    "fun_wink": "joobiwink2",
    "fun_thumbsup": "joobithumbsup",
    "fun_laughter": "joobilaughter",
    "fun_rage": "raiva",
    "fun_ok": "pepeok",
    "fun_stare": "pepestaring",
    "fun_banger": "pepebanger",
    "fun_gamer": "gamer",
    "fun_crewmate": "bluecrewmate",
}

custom_emoji_cache: dict[str, "discord.Emoji"] = {}


def E(key: str, fallback: str = "❓") -> str:
    emoji_name = CUSTOM_EMOJI_NAMES.get(key)
    if emoji_name:
        emoji = custom_emoji_cache.get(emoji_name)
        if emoji:
            return str(emoji)
    return fallback


_UNICODE_TO_EMOJI_KEY = {
    "✅": "success",
    "⭐": "star",
    "🎫": "ticket",
    "🔒": "lock",
    "🛡️": "shield",
    "⚠️": "warning",
    "❌": "error",
    "🔗": "link",
    "🌐": "web",
}


def themify(text: str) -> str:
    if not text:
        return text
    for glyph, key in _UNICODE_TO_EMOJI_KEY.items():
        if glyph in text:
            text = text.replace(glyph, E(key, glyph))
    return text


def base_embed(
    title: str,
    description: str = None,
    color: discord.Color = Theme.PRIMARY,
    guild: discord.Guild = None,
    timestamp: bool = True,
) -> discord.Embed:
    embed = discord.Embed(
        title=themify(title),
        description=themify(description),
        color=color,
        timestamp=datetime.datetime.now(timezone.utc) if timestamp else None,
    )
    footer_icon = guild.icon.url if guild and guild.icon else (bot.user.display_avatar.url if bot.user else None)
    bot_name = bot.user.name if bot.user else "BOB_BOT"
    if guild:
        embed.set_footer(text=f"◆ {guild.name} • {bot_name}", icon_url=footer_icon)
    else:
        embed.set_footer(text=f"◆ {bot_name}", icon_url=footer_icon)
    return embed


# =========================================================
# Rules text auto-formatter
# =========================================================
# Admins often paste rules as one flat paragraph like:
#   "1. Respect everyone Treat others with kindness. 2. Do not post ..."
# This detects a sequential numbered list embedded in the text (even
# without any line breaks) and rewrites it as one bolded item per line,
# separated by blank lines, so it always renders readably in Discord.
_RULES_NUMBER_PATTERN = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,2})\.\s+")


def format_rules_content(text: str) -> str:
    if not text:
        return text

    # Already has explicit numbered lines -> assume the admin formatted it
    # on purpose and leave it alone.
    if re.search(r"(?:\r?\n)\s*\d{1,2}\.\s", text):
        return text

    matches = list(_RULES_NUMBER_PATTERN.finditer(text))
    if len(matches) < 2:
        return text

    numbers = [int(m.group(1)) for m in matches]
    # Only treat this as a numbered list if it starts at 1 (or 0) and the
    # numbers are non-decreasing — avoids mangling text that just happens
    # to contain "24." somewhere in the middle.
    if numbers[0] not in (0, 1):
        return text
    if any(numbers[i] > numbers[i + 1] for i in range(len(numbers) - 1)):
        return text

    parts = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        parts.append(f"**{m.group(1)}.** {body}")

    return "\n\n".join(parts) if parts else text


# =========================================================
# i18n system — per-guild language, default English
# =========================================================
LANGUAGE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "language_config.json")
DEFAULT_LANGUAGE = "en"

# Add more languages here any time — just add a new top-level key to
# TRANSLATIONS with the same set of keys, and register it below.
AVAILABLE_LANGUAGES = {
    "en": {"name": "English", "flag": "🇬🇧"},
    "th": {"name": "ไทย", "flag": "🇹🇭"},
}


def load_language_config() -> dict:
    if os.path.exists(LANGUAGE_CONFIG_PATH):
        try:
            with open(LANGUAGE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read language_config.json — starting empty")
            return {}
    return {}


def save_language_config(config: dict) -> None:
    with open(LANGUAGE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# Structure: { "guild_id": "en" | "th" | ... }
language_config = load_language_config()


def get_guild_language(guild_id) -> str:
    return language_config.get(str(guild_id), DEFAULT_LANGUAGE)


def set_guild_language(guild_id, lang_code: str) -> None:
    language_config[str(guild_id)] = lang_code
    save_language_config(language_config)


TRANSLATIONS = {
    "en": {
        # verify
        "verify_not_configured_title": "Not configured yet",
        "verify_not_configured_desc": "❌ This server hasn't set up a verification role yet.\nAsk an admin to run `/setupverify`.",
        "verify_role_missing_title": "Role not found",
        "verify_role_missing_desc": "❌ The configured role couldn't be found (it may have been deleted). Please contact an admin.",
        "verify_already_title": "Already verified",
        "verify_already_desc": "✅ You're already verified.",
        "verify_success_title": "Verification successful 🎉",
        "verify_success_desc": "You've been given the {role} role. Welcome!",
        "verify_no_permission_title": "Something went wrong",
        "verify_no_permission_desc": "❌ The bot doesn't have permission to grant this role (make sure the bot's role is above the target role).",
        "verify_role_too_high_title": "Role too high",
        "verify_role_too_high_desc": "❌ The selected role is higher than or equal to the bot's role. Please move the bot's role above it first.",
        "verify_panel_title": "⭐ Verify to access this server",
        "verify_panel_desc": "Click the **Verify** button below to receive the {role} role.\n{divider}\nVerifying unlocks channels across the server for you ✅",
        "verify_setup_success_title": "Setup successful ✅",
        "verify_setup_sending": "Sending the verification message...",
        "verify_button_label": "Verify",

        # ticket
        "ticket_not_configured_title": "Not configured yet",
        "ticket_not_configured_desc": "❌ The ticket system isn't set up. Ask an admin to run `/setupticket`.",
        "ticket_category_missing_title": "Category not found",
        "ticket_category_missing_desc": "❌ The configured category couldn't be found (it may have been deleted). Please contact an admin.",
        "ticket_already_open_title": "You already have a ticket",
        "ticket_already_open_desc": "❌ You already have an open ticket at {channel}",
        "ticket_create_forbidden_title": "Something went wrong",
        "ticket_create_forbidden_desc": "❌ The bot doesn't have permission to create channels in this category. Please check the bot's permissions.",
        "ticket_create_failed_title": "Something went wrong",
        "ticket_create_failed_desc": "❌ Couldn't create the ticket channel. Please try again.",
        "ticket_channel_title": "🎫 Your ticket",
        "ticket_channel_desc": "Hi {member}, our team will be with you shortly.\n{divider}\nPlease describe your issue or request below and we'll get back to you as soon as we can 💬",
        "ticket_support_team_field": "👥 Support team",
        "ticket_opened_by_field": "👤 Opened by",
        "ticket_created_title": "Ticket created ✅",
        "ticket_created_desc": "Your ticket has been created at {channel}",
        "ticket_no_permission_title": "No permission",
        "ticket_no_permission_desc": "❌ You don't have permission to close this ticket",
        "ticket_closing_title": "🔒 Closing ticket",
        "ticket_closing_desc": "This channel will be deleted in 5 seconds by {member}, see you around {wave}",
        "ticket_closing_desc_simple": "This channel will be deleted in 5 seconds by {member}",
        "ticket_not_a_ticket_title": "Not a ticket channel",
        "ticket_not_a_ticket_desc": "❌ This isn't a ticket channel",
        "ticket_panel_title": "🎫 Contact support",
        "ticket_panel_desc": "Click the button below to open a private ticket with our team\n{divider}\nOur team will assist you as soon as possible 💬",
        "ticket_setup_success_title": "Setup successful ✅",
        "ticket_setup_sending": "Sending the ticket message...",
        "ticket_open_button": "Open ticket",
        "ticket_close_button": "Close ticket",

        # scripthub
        "scripthub_empty_title": "Nothing here yet",
        "scripthub_empty_desc": "❌ No items are available yet. Ask an admin to add one with `/scripthub_additem`.",
        "scripthub_item_missing_title": "Item not found",
        "scripthub_item_missing_desc": "❌ This item no longer exists (it may have been removed). Try pressing Refresh Menu and try again.",
        "scripthub_dm_default_content": "Here's your **{label}**",
        "scripthub_sent_title": "Sent ✅",
        "scripthub_sent_desc": "**{label}** has been sent to your DMs — check your inbox 📬 {clap}",
        "scripthub_dm_forbidden_title": "Couldn't send DM",
        "scripthub_dm_forbidden_desc": "❌ Please enable direct messages from members of this server first (check your Privacy Settings).",
        "scripthub_send_error_title": "Something went wrong",
        "scripthub_send_error_desc": "❌ An error occurred while sending the file. Please try again.",
        "scripthub_select_placeholder": "✨ Select a script/file you want...",
        "scripthub_no_items_option": "No items yet",
        "scripthub_refresh_button": "Refresh Menu",
        "scripthub_default_title": "SCRIPT HUB PANEL",
        "scripthub_default_desc": "Pick a script from the menu below and the bot will send it to your DMs instantly",
        "scripthub_how_to_use": "📥 **How to use:** click the ▾ menu, choose an item, and check your DMs",
        "scripthub_items_ready_footer": "{count} item(s) available",
        "scripthub_missing_data_title": "Missing information",
        "scripthub_missing_data_desc": "❌ Please provide at least one: a message (content) or a file attachment",
        "scripthub_not_setup_title": "Panel not created yet",
        "scripthub_not_setup_desc": "❌ This server doesn't have a panel yet. Please run `/scripthub_setup` first.",
        "scripthub_duplicate_title": "Name already used",
        "scripthub_duplicate_desc": "❌ An item with this name already exists. Please choose a different name.",
        "scripthub_full_title": "Panel is full",
        "scripthub_full_desc": "❌ This panel already has 25 items (Discord's limit).",
        "scripthub_creating_title": "Creating panel ✅",
        "scripthub_creating_desc": "Creating the file-sharing panel...",
        "scripthub_setup_done": "✅ Panel created. Use /scripthub_additem to keep adding items",
        "scripthub_item_added_title": "Item added ✅",
        "scripthub_item_added_desc": "Added **{label}** {note}",
        "scripthub_note_updated": "and the live panel has been updated",
        "scripthub_note_not_found": "(couldn't find the live panel — try pressing Refresh Menu on it)",
        "scripthub_no_items_title": "No items",
        "scripthub_no_items_desc": "❌ This panel doesn't have any items yet",
        "scripthub_item_not_found_title": "Item not found",
        "scripthub_item_not_found_desc": "❌ This item wasn't found",
        "scripthub_removed_title": "Item removed ✅",
        "scripthub_removed_desc": "Removed **{label}** {note}",
        "scripthub_note_removed_updated": "and the live panel has been updated",
        "scripthub_note_removed_not_found": "(try pressing Refresh Menu on the panel)",
        "scripthub_empty_list_title": "Empty",
        "scripthub_empty_list_desc": "📭 There are no items in this panel yet",
        "scripthub_list_title": "📋 Items in the file/template panel",
        "scripthub_kind_file": "📎 File",
        "scripthub_kind_text": "💬 Text",

        # AI system
        "ai_no_key_configured": "❌ GROQ_API_KEY hasn't been set on the server running this bot. Please ask the bot admin to set it in .env",
        "ai_rate_limited": "⏳ The AI is receiving too many requests right now. Please try again in a moment",
        "ai_generic_error": "❌ Couldn't reach the AI right now. Please try again",
        "ai_empty_reply": "🤔 Sorry, I couldn't come up with a reply. Try asking again",
        "ai_setup_success_title": "AI setup successful ✅",
        "ai_setup_success_desc": "The AI chat system is now enabled\nScope: {where}",
        "ai_setup_where_channel": "{channel}",
        "ai_setup_where_mention": "when mentioned (@bot) in any channel on this server",
        "ai_toggle_updated_title": "Updated",
        "ai_toggle_updated_desc": "AI chat system: {status}",
        "ai_toggle_on": "Enabled ✅",
        "ai_toggle_off": "Disabled ⛔",
        "ai_persona_success_title": "Persona updated ✅",
        "ai_persona_success_desc": "The AI's persona has been updated. The next message will use the new behavior",
        "ai_reset_success_title": "Memory cleared ✅",
        "ai_reset_success_desc": "The AI will start a fresh conversation in this channel (no old history carried over)",
        "ai_default_persona": (
            "You are BOB_BOT, an AI assistant for a Discord server. Speak casually, politely, "
            "and concisely — don't ramble. Reply in the same language the user writes in "
            "(default to English if unclear). If you're not sure about something, say so honestly "
            "instead of making things up, and avoid inappropriate content."
        ),

        # settings / language
        "settings_title": "⚙️ Server settings",
        "settings_desc": "Pick the language the bot should use for its messages in this server.\nCurrent language: **{current}**",
        "settings_select_placeholder": "🌐 Choose a language...",
        "settings_updated_title": "Language updated ✅",
        "settings_updated_desc": "The bot will now reply in **{language}** on this server.",
        "settings_no_permission_title": "No permission",
        "settings_no_permission_desc": "❌ You need the Manage Server permission to change this.",

        # rules
        "rules_setup_success_title": "Setup successful ✅",
        "rules_setup_sending": "Sending the rules panel...",
        "rules_setup_empty_note": "No languages added yet — use `/rules_edit` to add your first one.",
        "rules_placeholder_title": "📜 Server Rules",
        "rules_placeholder_desc": "No rules have been added yet. An admin can add sections with `/rules_edit`.",
        "rules_not_setup_title": "Rules panel not created yet",
        "rules_not_setup_desc": "❌ Please run `/rules_setup` first.",
        "rules_section_added_title": "Section added ✅",
        "rules_section_added_desc": "Added the **{name}** ({code}) rules section {note}",
        "rules_section_updated_desc": "Updated the **{name}** ({code}) rules section {note}",
        "rules_note_live_updated": "and updated the live panel",
        "rules_note_live_missing": "(couldn't find the live panel — run `/rules_setup` again if needed)",
        "rules_section_removed_title": "Section removed ✅",
        "rules_section_removed_desc": "Removed the **{code}** rules section {note}",
        "rules_section_not_found_title": "Section not found",
        "rules_section_not_found_desc": "❌ No rules section with the code **{code}** was found",
        "rules_no_sections_title": "No sections yet",
        "rules_no_sections_desc": "📭 There are no rules sections yet. Use `/rules_edit` to add one.",
        "rules_list_title": "📋 Rules sections in this server",
        "rules_too_many_title": "Too many sections",
        "rules_too_many_desc": "❌ A single message can only hold up to 10 embeds, and this panel already has {count}.",
        "rules_modal_title": "Editing: rules ({code})",
        "rules_modal_field_title": "Title",
        "rules_modal_field_description": "Description",
        "rules_modal_field_color": "Hex Color",
        "rules_modal_saved": "✅ Saved — here's a preview:",
        "rules_modal_author_title": "Editing: rules ({code}) — author",
        "rules_modal_field_author_name": "Author name",
        "rules_modal_field_icon_url": "Icon URL",
        "rules_modal_footer_title": "Editing: rules ({code}) — footer",
        "rules_modal_field_footer_text": "Footer text",
        "rules_modal_images_title": "Editing: rules ({code}) — images",
        "rules_modal_field_image_url": "Image URL",
        "rules_modal_field_thumbnail_url": "Thumbnail URL",

        # moderation & general (used across commands)
        "clear_success_title": "Messages cleared 🧹",
        "clear_success_desc": "Deleted **{count}** message(s), nice and tidy {clap}",
        "warn_title": "⚠️ Warning",
        "warn_desc": "{member} was warned by {mod}",
        "warn_reason_field": "📄 Reason",
        "warn_dm_title": "You've been warned ⚠️",
        "warn_dm_desc": "You were warned in **{guild}**",
        "kick_no_permission_title": "No permission",
        "kick_no_permission_desc": "❌ The bot doesn't have permission to kick this member (check the bot's role position)",
        "kick_success_title": "👢 Member kicked",
        "kick_success_desc": "{member} was kicked from the server",
        "ban_no_permission_title": "No permission",
        "ban_no_permission_desc": "❌ The bot doesn't have permission to ban this member (check the bot's role position)",
        "ban_success_title": "🔨 Member banned",
        "ban_success_desc": "{member} was banned from the server",
        "timeout_no_permission_title": "No permission",
        "timeout_no_permission_desc": "❌ The bot doesn't have permission to time out this member (check the bot's role position)",
        "timeout_success_title": "🔇 Member timed out",
        "timeout_success_desc": "{member} has been timed out for **{minutes} minute(s)**",
        "reason_not_specified": "No reason given",
        "addrole_success_title": "Role added ✅",
        "addrole_success_desc": "Added {role} to {member} {thumbsup}",
        "removerole_success_title": "Role removed ➖",
        "removerole_success_desc": "Removed {role} from {member} {ohno}",
        "nick_success_title": "Nickname changed ✏️",
        "nick_success_desc": "{member}'s nickname is now **{nick}** {laughter}",

        # role menu
        "rolemenu_created_sending": "Creating the role menu...",
        "rolemenu_created_note": "✅ Menu created. Use `/rolemenu_add message_id:{id}` to add role options",
        "rolemenu_role_too_high_title": "Role too high",
        "rolemenu_role_too_high_desc": "❌ The selected role is higher than or equal to the bot's role. Please move the bot's role above it first.",
        "rolemenu_not_found_title": "Menu not found",
        "rolemenu_not_found_desc": "❌ This menu wasn't found. Please create one with `/rolemenu_create` first.",
        "rolemenu_message_not_found_title": "Message not found",
        "rolemenu_message_not_found_desc": "❌ This message wasn't found in this channel. Please use the command in the same channel where the menu was created.",
        "rolemenu_bad_emoji_title": "Invalid emoji",
        "rolemenu_bad_emoji_desc": "❌ That emoji is invalid, or the bot can't use it",
        "rolemenu_option_added_title": "Option added ✅",
        "rolemenu_option_added_desc": "Added {emoji} → {role} to the menu",
        "rolemenu_option_not_found_title": "Option not found",
        "rolemenu_option_not_found_desc": "❌ This option wasn't found in the menu",
        "rolemenu_option_removed_title": "Option removed ✅",
        "rolemenu_option_removed_desc": "Removed {emoji} from the menu",
        "rolemenu_role_deleted": "(role deleted)",

        # general commands
        "ping_pong_title": "🏓 Pong!",
        "ping_pong_desc": "Current bot latency is **{ms}ms** {mood}",
        "userinfo_title": "👤 {member}'s info",
        "userinfo_username_field": "🏷️ Username",
        "userinfo_id_field": "🆔 ID",
        "userinfo_joined_field": "📥 Joined server on",
        "userinfo_created_field": "🎂 Account created on",
        "userinfo_roles_field": "🎭 Roles ({count})",
        "userinfo_no_roles": "None",
        "serverinfo_owner_field": "👑 Owner",
        "serverinfo_members_field": "👥 Members",
        "serverinfo_boosts_field": "🚀 Boosts",
        "serverinfo_created_field": "📅 Created on",
        "serverinfo_channels_field": "💬 Channels",
        "serverinfo_roles_field": "🎭 Roles",
        "poll_title": "📊 New poll",
        "poll_desc": "**{question}**\n{divider}\nReact below to vote {gamer}",
        "say_sent_title": "Message sent ✅",
        "say_sent_desc": "Your message was sent {wink}",
        "user_lookup_not_found_title": "User not found",
        "user_lookup_not_found_desc": "❌ No Roblox user named **{username}** was found. Please check the name/ID and try again.",
        "user_lookup_failed_title": "Couldn't fetch data",
        "user_lookup_failed_desc": (
            "❌ Couldn't fetch data from Rolimon's for **{name}** right now\n"
            "Possible reasons: this user has never been tracked by Rolimon's, or the API is temporarily "
            "rate-limited/blocked for some hosts (Rolimon's began blocking this API from some hosts in early 2026)"
        ),
        "user_lookup_no_data": "No data",
        "user_lookup_footer": "Stats updated a few seconds ago, refresh stats by visiting the profile page",

        # help
        "help_title": "📖 All BOB_BOT commands",
        "help_desc": "All commands available on this server",
        "help_moderation": "🛡️ Moderation",
        "help_roles": "🎭 Role management",
        "help_general": "💬 General",
        "help_roblox": "🟦 Roblox / Rolimon's",
        "help_roblox_desc": "`/user` — view a user's Roblox stats (RAP, Value, Collectibles, Value Rank)",
        "help_verify": "⭐ Verification",
        "help_verify_desc": "`/setupverify` — set up + send the verification message (button gives a role)",
        "help_rolemenu": "🎭 Reaction role menu",
        "help_ticket": "🎫 Ticket system",
        "help_scripthub": "📂 File/template panel (Script Hub)",
        "help_ai": "🤖 AI chat",
        "help_rules": "📜 Server rules",
        "help_settings": "⚙️ Settings",
        "help_settings_desc": "`/settings` — choose the language the bot replies in on this server",

        # errors
        "error_no_permission": "❌ You don't have permission to use this command",
        "error_generic_title": "Something went wrong",
        "error_generic_desc": "❌ An error occurred while running this command. Please try again",
    },
    "th": {
        "verify_not_configured_title": "ยังไม่ได้ตั้งค่า",
        "verify_not_configured_desc": "❌ ยังไม่ได้ตั้งค่ายศยืนยันตัวตนสำหรับเซิร์ฟเวอร์นี้\nกรุณาแจ้งแอดมินให้ใช้คำสั่ง `/setupverify`",
        "verify_role_missing_title": "ไม่พบยศ",
        "verify_role_missing_desc": "❌ ไม่พบยศที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน",
        "verify_already_title": "ยืนยันแล้ว",
        "verify_already_desc": "✅ คุณยืนยันตัวตนไปแล้ว",
        "verify_success_title": "ยืนยันตัวตนสำเร็จ 🎉",
        "verify_success_desc": "คุณได้รับยศ {role} เรียบร้อยแล้ว ยินดีต้อนรับ!",
        "verify_no_permission_title": "ผิดพลาด",
        "verify_no_permission_desc": "❌ บอทไม่มีสิทธิ์มอบยศนี้ (ตรวจสอบว่ายศของบอทอยู่สูงกว่ายศที่ต้องการมอบ)",
        "verify_role_too_high_title": "ยศสูงเกินไป",
        "verify_role_too_high_desc": "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน",
        "verify_panel_title": "⭐ ยืนยันตัวตนเพื่อเข้าใช้งานเซิร์ฟเวอร์",
        "verify_panel_desc": "คลิกปุ่ม **ยืนยันตัวตน** ด้านล่างเพื่อรับยศ {role}\n{divider}\nการยืนยันตัวตนจะช่วยปลดล็อกห้องต่าง ๆ ภายในเซิร์ฟเวอร์ให้คุณ ✅",
        "verify_setup_success_title": "ตั้งค่าสำเร็จ ✅",
        "verify_setup_sending": "กำลังส่งข้อความยืนยันตัวตน...",
        "verify_button_label": "ยืนยันตัวตน",

        "ticket_not_configured_title": "ยังไม่ได้ตั้งค่า",
        "ticket_not_configured_desc": "❌ ยังไม่ได้ตั้งค่าระบบทิกเก็ต กรุณาแจ้งแอดมินให้ใช้คำสั่ง `/setupticket`",
        "ticket_category_missing_title": "ไม่พบหมวดหมู่",
        "ticket_category_missing_desc": "❌ ไม่พบหมวดหมู่ที่ตั้งค่าไว้ (อาจถูกลบไปแล้ว) กรุณาแจ้งแอดมิน",
        "ticket_already_open_title": "มีทิกเก็ตอยู่แล้ว",
        "ticket_already_open_desc": "❌ คุณมีทิกเก็ตที่เปิดอยู่แล้วที่ {channel}",
        "ticket_create_forbidden_title": "ผิดพลาด",
        "ticket_create_forbidden_desc": "❌ บอทไม่มีสิทธิ์สร้างห้องในหมวดหมู่นี้ กรุณาตรวจสอบสิทธิ์ของบอท",
        "ticket_create_failed_title": "ผิดพลาด",
        "ticket_create_failed_desc": "❌ สร้างห้องทิกเก็ตไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        "ticket_channel_title": "🎫 ทิกเก็ตของคุณ",
        "ticket_channel_desc": "สวัสดี {member} ทีมงานจะเข้ามาช่วยเหลือคุณเร็ว ๆ นี้\n{divider}\nกรุณาอธิบายปัญหาหรือคำขอของคุณด้านล่าง ทีมงานจะรีบตอบกลับโดยเร็วที่สุด 💬",
        "ticket_support_team_field": "👥 ทีมงานที่ดูแล",
        "ticket_opened_by_field": "👤 เปิดโดย",
        "ticket_created_title": "เปิดทิกเก็ตสำเร็จ ✅",
        "ticket_created_desc": "เปิดทิกเก็ตแล้วที่ {channel}",
        "ticket_no_permission_title": "ไม่มีสิทธิ์",
        "ticket_no_permission_desc": "❌ คุณไม่มีสิทธิ์ปิดทิกเก็ตนี้",
        "ticket_closing_title": "🔒 กำลังปิดทิกเก็ต",
        "ticket_closing_desc": "ห้องนี้จะถูกลบใน 5 วินาที โดย {member} แล้วเจอกันใหม่ {wave}",
        "ticket_closing_desc_simple": "ห้องนี้จะถูกลบใน 5 วินาที โดย {member}",
        "ticket_not_a_ticket_title": "ไม่ใช่ห้องทิกเก็ต",
        "ticket_not_a_ticket_desc": "❌ ห้องนี้ไม่ใช่ห้องทิกเก็ต",
        "ticket_panel_title": "🎫 ติดต่อทีมงาน",
        "ticket_panel_desc": "กดปุ่มด้านล่างเพื่อเปิดทิกเก็ตส่วนตัวสำหรับติดต่อทีมงาน\n{divider}\nทีมงานจะเข้ามาช่วยเหลือคุณโดยเร็วที่สุด 💬",
        "ticket_setup_success_title": "ตั้งค่าสำเร็จ ✅",
        "ticket_setup_sending": "กำลังส่งข้อความระบบทิกเก็ต...",
        "ticket_open_button": "เปิดทิกเก็ต",
        "ticket_close_button": "ปิดทิกเก็ต",

        "scripthub_empty_title": "ยังไม่มีรายการ",
        "scripthub_empty_desc": "❌ ยังไม่มีรายการให้เลือก กรุณาแจ้งแอดมินให้เพิ่มด้วย `/scripthub_additem`",
        "scripthub_item_missing_title": "ไม่พบรายการ",
        "scripthub_item_missing_desc": "❌ ไม่พบรายการนี้แล้ว (อาจถูกลบไป) กรุณากด Refresh Menu แล้วลองใหม่",
        "scripthub_dm_default_content": "นี่คือไฟล์ **{label}** ของคุณค่ะ",
        "scripthub_sent_title": "ส่งสำเร็จ ✅",
        "scripthub_sent_desc": "ส่ง **{label}** เข้า DM ให้แล้ว ตรวจสอบกล่องข้อความส่วนตัวได้เลยครับ 📬 {clap}",
        "scripthub_dm_forbidden_title": "ส่ง DM ไม่ได้",
        "scripthub_dm_forbidden_desc": "❌ กรุณาเปิดรับข้อความส่วนตัวจากสมาชิกในเซิร์ฟเวอร์นี้ก่อน (ตั้งค่า Privacy Settings)",
        "scripthub_send_error_title": "เกิดข้อผิดพลาด",
        "scripthub_send_error_desc": "❌ เกิดข้อผิดพลาดระหว่างส่งไฟล์ กรุณาลองใหม่อีกครั้ง",
        "scripthub_select_placeholder": "✨ เลือกสคริปต์/ไฟล์ที่ต้องการ...",
        "scripthub_no_items_option": "ยังไม่มีรายการ",
        "scripthub_refresh_button": "Refresh Menu",
        "scripthub_default_title": "SCRIPT HUB PANEL",
        "scripthub_default_desc": "เลือกสคริปต์ที่ต้องการจากเมนูด้านล่าง แล้วบอทจะส่งเข้า DM ให้ทันที",
        "scripthub_how_to_use": "📥 **วิธีใช้:** กดที่เมนู ▾ เลือกรายการ รอรับข้อความทาง DM",
        "scripthub_items_ready_footer": "{count} รายการพร้อมให้บริการ",
        "scripthub_missing_data_title": "ข้อมูลไม่ครบ",
        "scripthub_missing_data_desc": "❌ ต้องใส่อย่างน้อยหนึ่งอย่าง: ข้อความ (content) หรือไฟล์แนบ (file)",
        "scripthub_not_setup_title": "ยังไม่ได้สร้างแผง",
        "scripthub_not_setup_desc": "❌ ยังไม่ได้สร้างแผงในเซิร์ฟเวอร์นี้ กรุณาใช้ `/scripthub_setup` ก่อน",
        "scripthub_duplicate_title": "ชื่อซ้ำ",
        "scripthub_duplicate_desc": "❌ มีรายการชื่อนี้อยู่แล้ว กรุณาใช้ชื่ออื่น",
        "scripthub_full_title": "เต็มแล้ว",
        "scripthub_full_desc": "❌ แผงนี้มีรายการครบ 25 แล้ว (ข้อจำกัดของ Discord)",
        "scripthub_creating_title": "กำลังสร้างแผง ✅",
        "scripthub_creating_desc": "กำลังสร้างแผงแจกไฟล์...",
        "scripthub_setup_done": "✅ สร้างแผงเรียบร้อย ใช้ /scripthub_additem เพื่อเพิ่มรายการต่อได้เลย",
        "scripthub_item_added_title": "เพิ่มรายการสำเร็จ ✅",
        "scripthub_item_added_desc": "เพิ่มรายการ **{label}** เรียบร้อย {note}",
        "scripthub_note_updated": "และอัปเดตแผงที่แสดงอยู่ให้แล้ว",
        "scripthub_note_not_found": "(หาแผงที่แสดงอยู่ไม่เจอ ลองกด Refresh Menu บนแผงเอง)",
        "scripthub_no_items_title": "ไม่มีรายการ",
        "scripthub_no_items_desc": "❌ ยังไม่มีรายการใด ๆ ในแผงนี้",
        "scripthub_item_not_found_title": "ไม่พบรายการ",
        "scripthub_item_not_found_desc": "❌ ไม่พบรายการนี้",
        "scripthub_removed_title": "ลบรายการสำเร็จ ✅",
        "scripthub_removed_desc": "ลบรายการ **{label}** แล้ว {note}",
        "scripthub_note_removed_updated": "และอัปเดตแผงที่แสดงอยู่ให้แล้ว",
        "scripthub_note_removed_not_found": "(ลองกด Refresh Menu บนแผงเอง)",
        "scripthub_empty_list_title": "ว่างเปล่า",
        "scripthub_empty_list_desc": "📭 ยังไม่มีรายการในแผงนี้",
        "scripthub_list_title": "📋 รายการในแผงแจกไฟล์/เทมเพลต",
        "scripthub_kind_file": "📎 ไฟล์",
        "scripthub_kind_text": "💬 ข้อความ",

        "ai_no_key_configured": "❌ ยังไม่ได้ตั้งค่า GROQ_API_KEY บนเซิร์ฟเวอร์ที่รันบอท กรุณาแจ้งผู้ดูแลบอทให้ตั้งค่าใน .env",
        "ai_rate_limited": "⏳ ตอนนี้ AI ถูกใช้งานเยอะเกินลิมิตชั่วคราว กรุณาลองใหม่อีกสักครู่",
        "ai_generic_error": "❌ เรียกใช้งาน AI ไม่สำเร็จตอนนี้ กรุณาลองใหม่อีกครั้ง",
        "ai_empty_reply": "🤔 ขอโทษด้วย ตอนนี้ตอบไม่ได้ ลองถามใหม่อีกครั้งนะ",
        "ai_setup_success_title": "ตั้งค่า AI สำเร็จ ✅",
        "ai_setup_success_desc": "เปิดใช้งานระบบ AI ตอบแชทแล้ว\nขอบเขตการตอบ: {where}",
        "ai_setup_where_channel": "{channel}",
        "ai_setup_where_mention": "การแท็ก @บอท ในห้องไหนก็ได้ของเซิร์ฟเวอร์นี้",
        "ai_toggle_updated_title": "อัปเดตแล้ว",
        "ai_toggle_updated_desc": "ระบบ AI ตอบแชท: {status}",
        "ai_toggle_on": "เปิดใช้งาน ✅",
        "ai_toggle_off": "ปิดใช้งาน ⛔",
        "ai_persona_success_title": "ตั้งค่าบุคลิกสำเร็จ ✅",
        "ai_persona_success_desc": "อัปเดต persona ของ AI แล้ว ข้อความถัดไปจะใช้กติกาใหม่นี้",
        "ai_reset_success_title": "ล้างความจำแล้ว ✅",
        "ai_reset_success_desc": "AI จะเริ่มบทสนทนาใหม่ในห้องนี้ (ไม่มีประวัติเก่าติดมา)",
        "ai_default_persona": (
            "คุณคือ BOB_BOT ผู้ช่วย AI ประจำเซิร์ฟเวอร์ Discord พูดจาเป็นกันเอง สุภาพ กระชับ ไม่ยืดเยื้อ "
            "ตอบเป็นภาษาไทยเป็นหลัก (ยกเว้นผู้ใช้พิมพ์ภาษาอื่นมาก็ตอบภาษานั้นได้) "
            "ถ้าไม่แน่ใจให้บอกตามตรงว่าไม่แน่ใจ อย่าแต่งข้อมูลขึ้นมาเอง และหลีกเลี่ยงเนื้อหาที่ไม่เหมาะสม"
        ),

        "settings_title": "⚙️ ตั้งค่าเซิร์ฟเวอร์",
        "settings_desc": "เลือกภาษาที่ต้องการให้บอทใช้ตอบในเซิร์ฟเวอร์นี้\nภาษาปัจจุบัน: **{current}**",
        "settings_select_placeholder": "🌐 เลือกภาษา...",
        "settings_updated_title": "เปลี่ยนภาษาแล้ว ✅",
        "settings_updated_desc": "บอทจะตอบเป็น **{language}** ในเซิร์ฟเวอร์นี้ต่อจากนี้",
        "settings_no_permission_title": "ไม่มีสิทธิ์",
        "settings_no_permission_desc": "❌ คุณต้องมีสิทธิ์ Manage Server ถึงจะเปลี่ยนค่านี้ได้",

        "rules_setup_success_title": "ตั้งค่าสำเร็จ ✅",
        "rules_setup_sending": "กำลังส่งแผงกฎเซิร์ฟเวอร์...",
        "rules_setup_empty_note": "ยังไม่มีภาษาไหนถูกเพิ่ม — ใช้ `/rules_edit` เพื่อเพิ่มภาษาแรก",
        "rules_placeholder_title": "📜 กฎของเซิร์ฟเวอร์",
        "rules_placeholder_desc": "ยังไม่มีการเพิ่มกฎ แอดมินสามารถเพิ่มได้ด้วย `/rules_edit`",
        "rules_not_setup_title": "ยังไม่ได้สร้างแผงกฎ",
        "rules_not_setup_desc": "❌ กรุณาใช้ `/rules_setup` ก่อน",
        "rules_section_added_title": "เพิ่มส่วนกฎสำเร็จ ✅",
        "rules_section_added_desc": "เพิ่มกฎภาษา **{name}** ({code}) แล้ว {note}",
        "rules_section_updated_desc": "อัปเดตกฎภาษา **{name}** ({code}) แล้ว {note}",
        "rules_note_live_updated": "และอัปเดตแผงที่แสดงอยู่ให้แล้ว",
        "rules_note_live_missing": "(หาแผงที่แสดงอยู่ไม่เจอ ลองรัน `/rules_setup` อีกครั้ง)",
        "rules_section_removed_title": "ลบส่วนกฎสำเร็จ ✅",
        "rules_section_removed_desc": "ลบกฎภาษา **{code}** แล้ว {note}",
        "rules_section_not_found_title": "ไม่พบส่วนกฎนี้",
        "rules_section_not_found_desc": "❌ ไม่พบกฎภาษา **{code}**",
        "rules_no_sections_title": "ยังไม่มีข้อมูล",
        "rules_no_sections_desc": "📭 ยังไม่มีส่วนกฎใด ๆ ใช้ `/rules_edit` เพื่อเพิ่ม",
        "rules_list_title": "📋 รายการกฎในเซิร์ฟเวอร์นี้",
        "rules_too_many_title": "มีภาษาเยอะเกินไป",
        "rules_too_many_desc": "❌ หนึ่งข้อความแสดง embed ได้สูงสุด 10 อัน ตอนนี้แผงนี้มี {count} แล้ว",
        "rules_modal_title": "Editing: rules ({code})",
        "rules_modal_field_title": "Title",
        "rules_modal_field_description": "Description",
        "rules_modal_field_color": "Hex Color",
        "rules_modal_saved": "✅ บันทึกแล้ว — ตัวอย่าง:",
        "rules_modal_author_title": "Editing: rules ({code}) — author",
        "rules_modal_field_author_name": "Author name",
        "rules_modal_field_icon_url": "Icon URL",
        "rules_modal_footer_title": "Editing: rules ({code}) — footer",
        "rules_modal_field_footer_text": "Footer text",
        "rules_modal_images_title": "Editing: rules ({code}) — images",
        "rules_modal_field_image_url": "Image URL",
        "rules_modal_field_thumbnail_url": "Thumbnail URL",

        "clear_success_title": "ลบข้อความสำเร็จ 🧹",
        "clear_success_desc": "ลบข้อความไปแล้ว **{count}** ข้อความ สะอาดเอี่ยม {clap}",
        "warn_title": "⚠️ คำเตือน",
        "warn_desc": "{member} ถูกเตือนโดย {mod}",
        "warn_reason_field": "📄 เหตุผล",
        "warn_dm_title": "คุณถูกเตือน ⚠️",
        "warn_dm_desc": "คุณถูกเตือนในเซิร์ฟเวอร์ **{guild}**",
        "kick_no_permission_title": "ไม่มีสิทธิ์",
        "kick_no_permission_desc": "❌ บอทไม่มีสิทธิ์เตะสมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)",
        "kick_success_title": "👢 เตะสมาชิกออกแล้ว",
        "kick_success_desc": "{member} ถูกเตะออกจากเซิร์ฟเวอร์",
        "ban_no_permission_title": "ไม่มีสิทธิ์",
        "ban_no_permission_desc": "❌ บอทไม่มีสิทธิ์แบนสมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)",
        "ban_success_title": "🔨 แบนสมาชิกแล้ว",
        "ban_success_desc": "{member} ถูกแบนออกจากเซิร์ฟเวอร์",
        "timeout_no_permission_title": "ไม่มีสิทธิ์",
        "timeout_no_permission_desc": "❌ บอทไม่มีสิทธิ์ timeout สมาชิกคนนี้ (ตรวจสอบลำดับยศของบอท)",
        "timeout_success_title": "🔇 ปิดปากชั่วคราว",
        "timeout_success_desc": "{member} ถูกปิดปากเป็นเวลา **{minutes} นาที**",
        "reason_not_specified": "ไม่ระบุเหตุผล",
        "addrole_success_title": "เพิ่มยศสำเร็จ ✅",
        "addrole_success_desc": "เพิ่มยศ {role} ให้ {member} แล้ว {thumbsup}",
        "removerole_success_title": "ลบยศสำเร็จ ➖",
        "removerole_success_desc": "ลบยศ {role} ออกจาก {member} แล้ว {ohno}",
        "nick_success_title": "เปลี่ยนชื่อเล่นสำเร็จ ✏️",
        "nick_success_desc": "เปลี่ยนชื่อเล่นของ {member} เป็น **{nick}** แล้ว {laughter}",

        "rolemenu_created_sending": "กำลังสร้างเมนูรับยศ...",
        "rolemenu_created_note": "✅ สร้างเมนูเรียบร้อย ใช้คำสั่ง `/rolemenu_add message_id:{id}` เพื่อเพิ่มตัวเลือกยศ",
        "rolemenu_role_too_high_title": "ยศสูงเกินไป",
        "rolemenu_role_too_high_desc": "❌ ยศที่เลือกอยู่สูงกว่าหรือเท่ากับยศของบอท กรุณาเลื่อนยศบอทให้สูงกว่ายศนี้ก่อน",
        "rolemenu_not_found_title": "ไม่พบเมนู",
        "rolemenu_not_found_desc": "❌ ไม่พบเมนูนี้ กรุณาสร้างด้วย `/rolemenu_create` ก่อน",
        "rolemenu_message_not_found_title": "ไม่พบข้อความ",
        "rolemenu_message_not_found_desc": "❌ ไม่พบข้อความนี้ในห้องนี้ กรุณาใช้คำสั่งในห้องเดียวกับที่สร้างเมนู",
        "rolemenu_bad_emoji_title": "อิโมจิไม่ถูกต้อง",
        "rolemenu_bad_emoji_desc": "❌ อิโมจิไม่ถูกต้อง หรือบอทใช้อิโมจินี้ไม่ได้",
        "rolemenu_option_added_title": "เพิ่มตัวเลือกสำเร็จ ✅",
        "rolemenu_option_added_desc": "เพิ่ม {emoji} → {role} เข้าเมนูแล้ว",
        "rolemenu_option_not_found_title": "ไม่พบตัวเลือก",
        "rolemenu_option_not_found_desc": "❌ ไม่พบตัวเลือกนี้ในเมนู",
        "rolemenu_option_removed_title": "ลบตัวเลือกสำเร็จ ✅",
        "rolemenu_option_removed_desc": "ลบ {emoji} ออกจากเมนูแล้ว",
        "rolemenu_role_deleted": "(ยศถูกลบ)",

        "ping_pong_title": "🏓 Pong!",
        "ping_pong_desc": "ความหน่วงของบอทตอนนี้อยู่ที่ **{ms}ms** {mood}",
        "userinfo_title": "👤 ข้อมูลของ {member}",
        "userinfo_username_field": "🏷️ ชื่อผู้ใช้",
        "userinfo_id_field": "🆔 ID",
        "userinfo_joined_field": "📥 เข้าร่วมเซิร์ฟเวอร์เมื่อ",
        "userinfo_created_field": "🎂 สร้างบัญชีเมื่อ",
        "userinfo_roles_field": "🎭 ยศ ({count})",
        "userinfo_no_roles": "ไม่มี",
        "serverinfo_owner_field": "👑 เจ้าของ",
        "serverinfo_members_field": "👥 จำนวนสมาชิก",
        "serverinfo_boosts_field": "🚀 บูสต์",
        "serverinfo_created_field": "📅 สร้างเมื่อ",
        "serverinfo_channels_field": "💬 จำนวนห้อง",
        "serverinfo_roles_field": "🎭 จำนวนยศ",
        "poll_title": "📊 โพลใหม่",
        "poll_desc": "**{question}**\n{divider}\nกดรีแอคด้านล่างเพื่อโหวต {gamer}",
        "say_sent_title": "ส่งข้อความแล้ว ✅",
        "say_sent_desc": "ข้อความถูกส่งเรียบร้อย {wink}",
        "user_lookup_not_found_title": "ไม่พบผู้ใช้",
        "user_lookup_not_found_desc": "❌ ไม่พบผู้ใช้ Roblox ชื่อ **{username}** กรุณาตรวจสอบชื่อ/ID อีกครั้ง",
        "user_lookup_failed_title": "ดึงข้อมูลไม่สำเร็จ",
        "user_lookup_failed_desc": (
            "❌ ไม่สามารถดึงข้อมูลจาก Rolimon's สำหรับ **{name}** ได้ในตอนนี้\n"
            "สาเหตุที่เป็นไปได้: ผู้ใช้นี้ยังไม่เคยถูกเก็บสถิติใน Rolimon's หรือ API ถูกจำกัด/บล็อกการเข้าถึงชั่วคราว "
            "(Rolimon's เริ่มบล็อกการเรียก API นี้จากบางโฮสต์ตั้งแต่ต้นปี 2569)"
        ),
        "user_lookup_no_data": "ไม่มีข้อมูล",
        "user_lookup_footer": "Stats updated a few seconds ago, refresh stats by visiting the profile page",

        "help_title": "📖 คำสั่งทั้งหมดของ BOB_BOT",
        "help_desc": "รวมทุกคำสั่งที่ใช้งานได้ในเซิร์ฟเวอร์นี้",
        "help_moderation": "🛡️ Moderation",
        "help_roles": "🎭 จัดการยศ",
        "help_general": "💬 ทั่วไป",
        "help_roblox": "🟦 Roblox / Rolimon's",
        "help_roblox_desc": "`/user` — ดูสถิติ Roblox ของผู้ใช้ (RAP, Value, Collectibles, Value Rank)",
        "help_verify": "⭐ ยืนยันตัวตน",
        "help_verify_desc": "`/setupverify` — ตั้งค่า+ส่งข้อความยืนยันตัวตน (กดปุ่มรับยศ)",
        "help_rolemenu": "🎭 เมนูรับยศด้วยรีแอค",
        "help_ticket": "🎫 ระบบทิกเก็ต",
        "help_scripthub": "📂 แผงแจกไฟล์/เทมเพลต (Script Hub)",
        "help_ai": "🤖 AI ตอบแชท",
        "help_rules": "📜 กฎเซิร์ฟเวอร์",
        "help_settings": "⚙️ ตั้งค่า",
        "help_settings_desc": "`/settings` — เลือกภาษาที่บอทจะใช้ตอบในเซิร์ฟเวอร์นี้",

        "error_no_permission": "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
        "error_generic_title": "เกิดข้อผิดพลาด",
        "error_generic_desc": "❌ เกิดข้อผิดพลาดขณะทำคำสั่งนี้ กรุณาลองใหม่อีกครั้ง",
    },
}


def L(guild_id, key: str, **kwargs) -> str:
    """Translate `key` into the language configured for `guild_id` (default English)."""
    lang = get_guild_language(guild_id)
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANGUAGE]
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


class LanguageSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        options = [
            discord.SelectOption(
                label=info["name"],
                value=code,
                emoji=info["flag"],
                default=(code == get_guild_language(guild_id)),
            )
            for code, info in AVAILABLE_LANGUAGES.items()
        ]
        super().__init__(
            placeholder=L(guild_id, "settings_select_placeholder"),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"bobbot_settings_lang_{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                embed=base_embed(
                    L(self.guild_id, "settings_no_permission_title"),
                    L(self.guild_id, "settings_no_permission_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        lang_code = self.values[0]
        set_guild_language(self.guild_id, lang_code)
        lang_name = AVAILABLE_LANGUAGES[lang_code]["name"]

        await interaction.response.send_message(
            embed=base_embed(
                L(self.guild_id, "settings_updated_title"),
                L(self.guild_id, "settings_updated_desc", language=lang_name),
                color=Theme.SUCCESS,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )


class SettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=120)
        self.add_item(LanguageSelect(guild_id))


# ---------------------------------------------------------
# Keep-alive HTTP server (for Render Free Plan)
# ---------------------------------------------------------
keep_alive_app = Flask(__name__)


@keep_alive_app.route("/")
def keep_alive_home():
    return "BOB_BOT is alive!", 200


def run_keep_alive_server():
    port = int(os.getenv("PORT", 10000))
    keep_alive_app.run(host="0.0.0.0", port=port)


def start_keep_alive():
    thread = threading.Thread(target=run_keep_alive_server, daemon=True)
    thread.start()
    logger.info("Keep-alive HTTP server started")


TOKEN = os.getenv("BOT_TOKEN")

# ---------------------------------------------------------
# AI chat system (Groq API)
# ---------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "openai/gpt-oss-120b")

groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    logger.warning("GROQ_API_KEY not found — the AI chat system won't work until it's set in .env")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
bot.startup_done = False

# ---------- Verification role config ----------
VERIFY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "verify_config.json")


def load_verify_config() -> dict:
    if os.path.exists(VERIFY_CONFIG_PATH):
        try:
            with open(VERIFY_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read verify_config.json — starting empty")
            return {}
    return {}


def save_verify_config(config: dict) -> None:
    with open(VERIFY_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


verify_config = load_verify_config()  # { "guild_id": role_id }


# ---------- Reaction role menu config ----------
REACTIONROLE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "reactionrole_config.json")


def load_reactionrole_config() -> dict:
    if os.path.exists(REACTIONROLE_CONFIG_PATH):
        try:
            with open(REACTIONROLE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read reactionrole_config.json — starting empty")
            return {}
    return {}


def save_reactionrole_config(config: dict) -> None:
    with open(REACTIONROLE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


reactionrole_config = load_reactionrole_config()


# ---------- Ticket config ----------
TICKET_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ticket_config.json")


def load_ticket_config() -> dict:
    if os.path.exists(TICKET_CONFIG_PATH):
        try:
            with open(TICKET_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read ticket_config.json — starting empty")
            return {}
    return {}


def save_ticket_config(config: dict) -> None:
    with open(TICKET_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


ticket_config = load_ticket_config()


# ---------- Script/File hub panel config ----------
SCRIPTHUB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scripthub_config.json")
SCRIPTHUB_FILES_DIR = os.path.join(os.path.dirname(__file__), "scripthub_files")
os.makedirs(SCRIPTHUB_FILES_DIR, exist_ok=True)


def load_scripthub_config() -> dict:
    if os.path.exists(SCRIPTHUB_CONFIG_PATH):
        try:
            with open(SCRIPTHUB_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read scripthub_config.json — starting empty")
            return {}
    return {}


def save_scripthub_config(config: dict) -> None:
    with open(SCRIPTHUB_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


scripthub_config = load_scripthub_config()


# ---------- AI chat config ----------
AI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ai_config.json")


def load_ai_config() -> dict:
    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read ai_config.json — starting empty")
            return {}
    return {}


def save_ai_config(config: dict) -> None:
    with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


ai_config = load_ai_config()

AI_HISTORY_LIMIT = 12
ai_conversations: dict[int, deque] = {}


def get_ai_history(channel_id: int) -> deque:
    if channel_id not in ai_conversations:
        ai_conversations[channel_id] = deque(maxlen=AI_HISTORY_LIMIT)
    return ai_conversations[channel_id]


# ---------- Rules panel config ----------
RULES_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "rules_config.json")


def load_rules_config() -> dict:
    if os.path.exists(RULES_CONFIG_PATH):
        try:
            with open(RULES_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read rules_config.json — starting empty")
            return {}
    return {}


def save_rules_config(config: dict) -> None:
    with open(RULES_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# Structure: { "guild_id": {
#   "channel_id": int, "message_id": int,
#   "sections": [ {"code": "EN", "name": "English", "color": int, "content": str} ]
# } }
rules_config = load_rules_config()


async def generate_ai_reply(guild_id: int, channel_id: int, persona: str, user_name: str, user_message: str) -> str:
    """Call the Groq API to generate a reply, using the channel's short-term history as context."""
    if not groq_client:
        return L(guild_id, "ai_no_key_configured")

    history = get_ai_history(channel_id)
    new_turn = {"role": "user", "content": f"{user_name}: {user_message}"}
    messages = [{"role": "system", "content": persona}] + list(history) + [new_turn]

    def call_api():
        return groq_client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
        )

    max_retries = 3
    response = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.to_thread(call_api)
            break
        except RateLimitError as e:
            if attempt == max_retries:
                logger.warning(f"Groq API rate limit hit — gave up after {max_retries} attempts: {e}")
                return L(guild_id, "ai_rate_limited")
            wait_seconds = 2 * attempt
            logger.warning(f"Groq API rate limited — waiting {wait_seconds}s before retry ({attempt}/{max_retries})")
            await asyncio.sleep(wait_seconds)
        except APIStatusError as e:
            logger.exception(f"Groq API returned an error: {e}")
            return L(guild_id, "ai_generic_error")
        except Exception:
            logger.exception("Failed to call Groq API (unexpected)")
            return L(guild_id, "ai_generic_error")

    reply_text = (response.choices[0].message.content or "").strip() if response else ""
    if not reply_text:
        reply_text = L(guild_id, "ai_empty_reply")

    history.append(new_turn)
    history.append({"role": "assistant", "content": reply_text})
    return reply_text


def split_for_discord(text: str, limit: int = 1900) -> list:
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def safe_filename_part(text: str, fallback: str = "item") -> str:
    cleaned = "".join(c for c in text if c.isalnum() or c in "._- ").strip()
    return cleaned or fallback


# =========================================================
# Roblox / Rolimon's lookups (RAP, Value, Collectibles, Value Rank)
# =========================================================
ROLIMONS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.rolimons.com/",
}


async def resolve_roblox_user(query: str) -> dict | None:
    query = query.strip()
    try:
        async with aiohttp.ClientSession() as session:
            if query.isdigit():
                async with session.get(
                    f"https://users.roblox.com/v1/users/{query}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return {
                        "id": data["id"],
                        "name": data["name"],
                        "display_name": data.get("displayName") or data["name"],
                    }
            else:
                payload = {"usernames": [query], "excludeBannedUsers": False}
                async with session.post(
                    "https://users.roblox.com/v1/usernames/users",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    results = data.get("data") or []
                    if not results:
                        return None
                    found = results[0]
                    return {
                        "id": found["id"],
                        "name": found["name"],
                        "display_name": found.get("displayName") or found["name"],
                    }
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("Failed to resolve Roblox user")
        return None


async def fetch_rolimons_playerinfo(user_id: int) -> dict | None:
    url = f"https://api.rolimons.com/players/v1/playerinfo/{user_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=ROLIMONS_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Rolimon's playerinfo returned HTTP {resp.status} for user {user_id}")
                    return None
                data = await resp.json()
                if data.get("success") is False:
                    return None
                return data
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("Failed to call Rolimon's playerinfo")
        return None


async def fetch_rolimons_collectibles(user_id: int) -> int | None:
    url = f"https://api.rolimons.com/players/v1/playerassets/{user_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=ROLIMONS_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("success") is False:
                    return None
                assets = data.get("playerAssets") or data.get("assets") or {}
                if isinstance(assets, dict):
                    total = 0
                    for asset_instances in assets.values():
                        total += len(asset_instances) if isinstance(asset_instances, list) else 1
                    return total
                return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("Failed to call Rolimon's playerassets")
        return None


async def fetch_roblox_avatar(user_id: int) -> str | None:
    url = (
        "https://thumbnails.roblox.com/v1/users/avatar"
        f"?userIds={user_id}&size=250x250&format=Png&isCircular=false"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                results = data.get("data") or []
                if results:
                    return results[0].get("imageUrl")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    return None


class RolimonsProfileView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Profile",
                emoji="👤",
                style=discord.ButtonStyle.link,
                url=f"https://www.rolimons.com/player/{user_id}",
            )
        )
        self.add_item(
            discord.ui.Button(
                label="History",
                emoji="📜",
                style=discord.ButtonStyle.link,
                url=f"https://www.rolimons.com/player/{user_id}",
            )
        )


# =========================================================
# Verification system — button grants a role instantly
# =========================================================
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        emoji="⭐",
        custom_id="bobbot_verify_button",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        role_id = verify_config.get(str(guild_id))

        if not role_id:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "verify_not_configured_title"),
                    L(guild_id, "verify_not_configured_desc"),
                    color=Theme.WARNING,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "verify_role_missing_title"),
                    L(guild_id, "verify_role_missing_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "verify_already_title"),
                    L(guild_id, "verify_already_desc"),
                    color=Theme.SUCCESS,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Verified via button")
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "verify_success_title"),
                    L(guild_id, "verify_success_desc", role=role.mention),
                    color=Theme.SUCCESS,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "verify_no_permission_title"),
                    L(guild_id, "verify_no_permission_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )


# =========================================================
# Ticket system
# =========================================================
class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="bobbot_ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        guild_id = guild.id
        conf = ticket_config.get(str(guild_id))

        if not conf or not conf.get("category_id"):
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "ticket_not_configured_title"),
                    L(guild_id, "ticket_not_configured_desc"),
                    color=Theme.WARNING,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        category = guild.get_channel(int(conf["category_id"]))
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "ticket_category_missing_title"),
                    L(guild_id, "ticket_category_missing_desc"),
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        support_role = guild.get_role(int(conf["support_role_id"])) if conf.get("support_role_id") else None

        existing_name = f"ticket-{interaction.user.id}"
        for ch in category.text_channels:
            if ch.name == existing_name:
                await interaction.response.send_message(
                    embed=base_embed(
                        L(guild_id, "ticket_already_open_title"),
                        L(guild_id, "ticket_already_open_desc", channel=ch.mention),
                        color=Theme.WARNING,
                        guild=guild,
                    ),
                    ephemeral=True,
                )
                return

        await interaction.response.defer(ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
            ),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

        try:
            ticket_channel = await guild.create_text_channel(
                name=existing_name,
                category=category,
                overwrites=overwrites,
                topic=f"ticket_owner_id:{interaction.user.id}",
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=base_embed(
                    L(guild_id, "ticket_create_forbidden_title"),
                    L(guild_id, "ticket_create_forbidden_desc"),
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception(f"Failed to create ticket channel for {interaction.user}")
            await interaction.followup.send(
                embed=base_embed(
                    L(guild_id, "ticket_create_failed_title"),
                    L(guild_id, "ticket_create_failed_desc"),
                    color=Theme.DANGER,
                    guild=guild,
                ),
                ephemeral=True,
            )
            return

        embed = base_embed(
            L(guild_id, "ticket_channel_title"),
            L(guild_id, "ticket_channel_desc", member=interaction.user.mention, divider=Theme.DIVIDER),
            color=Theme.TICKET,
            guild=guild,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if support_role:
            embed.add_field(name=L(guild_id, "ticket_support_team_field"), value=support_role.mention, inline=True)
        embed.add_field(name=L(guild_id, "ticket_opened_by_field"), value=interaction.user.mention, inline=True)

        await ticket_channel.send(
            content=support_role.mention if support_role else None,
            embed=embed,
            view=TicketCloseView(),
        )
        await interaction.followup.send(
            embed=base_embed(
                L(guild_id, "ticket_created_title"),
                L(guild_id, "ticket_created_desc", channel=ticket_channel.mention),
                color=Theme.SUCCESS,
                guild=guild,
            ),
            ephemeral=True,
        )


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="bobbot_ticket_close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild_id = interaction.guild.id
        conf = ticket_config.get(str(guild_id), {})
        support_role_id = conf.get("support_role_id")

        is_owner = False
        if channel.topic and "ticket_owner_id:" in channel.topic:
            try:
                owner_id = int(channel.topic.split("ticket_owner_id:")[1].strip())
                is_owner = owner_id == interaction.user.id
            except ValueError:
                pass

        has_support_role = bool(
            support_role_id and interaction.guild.get_role(int(support_role_id)) in interaction.user.roles
        )
        can_close = is_owner or has_support_role or interaction.user.guild_permissions.manage_channels

        if not can_close:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "ticket_no_permission_title"),
                    L(guild_id, "ticket_no_permission_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=base_embed(
                L(guild_id, "ticket_closing_title"),
                L(guild_id, "ticket_closing_desc", member=interaction.user.mention, wave=E("fun_wink", "👋")),
                color=Theme.WARNING,
                guild=interaction.guild,
            )
        )
        logger.info(f"Ticket {channel.name} closed by {interaction.user}")
        await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.NotFound:
            pass


# =========================================================
# Script/File hub panel
# =========================================================
class ScriptHubSelect(discord.ui.Select):
    def __init__(self, guild_id: int, items: list):
        options = [
            discord.SelectOption(
                label=item["label"][:100],
                description=(item.get("description") or "")[:100],
                value=item["label"],
                emoji="📎" if item.get("file_path") else "💬",
            )
            for item in items[:25]
        ]
        if not options:
            options = [discord.SelectOption(label=L(guild_id, "scripthub_no_items_option"), value="__empty__", emoji="📭")]
        super().__init__(
            placeholder=L(guild_id, "scripthub_select_placeholder"),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"scripthub_select_{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        guild_id = self.guild_id
        if self.values[0] == "__empty__":
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "scripthub_empty_title"),
                    L(guild_id, "scripthub_empty_desc"),
                    color=Theme.WARNING,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        conf = scripthub_config.get(str(guild_id), {})
        items = conf.get("items", [])
        chosen = next((i for i in items if i["label"] == self.values[0]), None)

        if not chosen:
            await interaction.response.send_message(
                embed=base_embed(
                    L(guild_id, "scripthub_item_missing_title"),
                    L(guild_id, "scripthub_item_missing_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            files = None
            file_path = chosen.get("file_path")
            if file_path and os.path.exists(file_path):
                files = [discord.File(file_path, filename=chosen.get("file_name") or os.path.basename(file_path))]

            dm_content = chosen.get("content") or L(guild_id, "scripthub_dm_default_content", label=chosen["label"])
            await interaction.user.send(content=dm_content, files=files)
            await interaction.followup.send(
                embed=base_embed(
                    L(guild_id, "scripthub_sent_title"),
                    L(guild_id, "scripthub_sent_desc", label=chosen["label"], clap=E("fun_clap", "👏")),
                    color=Theme.SUCCESS,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=base_embed(
                    L(guild_id, "scripthub_dm_forbidden_title"),
                    L(guild_id, "scripthub_dm_forbidden_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception(f"Failed to send scripthub file: {chosen['label']}")
            await interaction.followup.send(
                embed=base_embed(
                    L(guild_id, "scripthub_send_error_title"),
                    L(guild_id, "scripthub_send_error_desc"),
                    color=Theme.DANGER,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )


class ScriptHubRefreshButton(discord.ui.Button):
    def __init__(self, guild_id: int):
        super().__init__(
            label=L(guild_id, "scripthub_refresh_button"),
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            custom_id=f"scripthub_refresh_{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        conf = scripthub_config.get(str(self.guild_id), {})
        items = conf.get("items", [])
        new_view = ScriptHubView(self.guild_id, items)
        await interaction.response.edit_message(view=new_view)


class ScriptHubView(discord.ui.View):
    def __init__(self, guild_id: int, items: list):
        super().__init__(timeout=None)
        self.add_item(ScriptHubSelect(guild_id, items))
        self.add_item(ScriptHubRefreshButton(guild_id))


def build_scripthub_embed(guild_id: int, conf: dict) -> discord.Embed:
    title = conf.get("title") or L(guild_id, "scripthub_default_title")
    description = conf.get("description") or L(guild_id, "scripthub_default_desc")
    embed = discord.Embed(
        title=themify(f"📂 {title}"),
        description=themify(
            f"{description}\n{Theme.DIVIDER}\n{L(guild_id, 'scripthub_how_to_use')}"
        ),
        color=Theme.SCRIPTHUB,
        timestamp=datetime.datetime.now(timezone.utc),
    )
    if conf.get("image_url"):
        embed.set_image(url=conf["image_url"])
    embed.set_thumbnail(url=bot.user.display_avatar.url if bot.user else None)
    items_count = len(conf.get("items", []))
    embed.set_footer(
        text=f"◆ {bot.user.name if bot.user else 'BOB_BOT'} • {L(guild_id, 'scripthub_items_ready_footer', count=items_count)}",
        icon_url=bot.user.display_avatar.url if bot.user else None,
    )
    return embed


def build_single_rules_embed(idx: int, section: dict) -> discord.Embed:
    color_value = section.get("color")
    color = discord.Color(color_value) if color_value else Theme.RULES_PALETTE[idx % len(Theme.RULES_PALETTE)]
    embed = discord.Embed(
        title=f"[{section['code']}] {section['name']}",
        description=format_rules_content(section["content"]),
        color=color,
    )
    if section.get("author_name"):
        embed.set_author(name=section["author_name"], icon_url=section.get("author_icon_url") or None)
    if section.get("footer_text"):
        embed.set_footer(text=section["footer_text"], icon_url=section.get("footer_icon_url") or None)
    else:
        embed.set_footer(text=f"◆ {section['code']} • {bot.user.name if bot.user else 'BOB_BOT'}")
    if section.get("image_url"):
        embed.set_image(url=section["image_url"])
    if section.get("thumbnail_url"):
        embed.set_thumbnail(url=section["thumbnail_url"])
    return embed


def build_rules_embeds(guild_id: int, conf: dict) -> list[discord.Embed]:
    """Build one embed per language section, in the order they were added."""
    sections = conf.get("sections", [])
    if not sections:
        return [
            base_embed(
                L(guild_id, "rules_placeholder_title"),
                L(guild_id, "rules_placeholder_desc"),
                color=Theme.PRIMARY,
                guild=None,
                timestamp=False,
            )
        ]
    return [build_single_rules_embed(idx, section) for idx, section in enumerate(sections)]


def get_rules_section(conf: dict, code_upper: str) -> dict | None:
    return next((s for s in conf.get("sections", []) if s["code"] == code_upper), None)


async def sync_rules_panel(guild_id: int, guild: discord.Guild, conf: dict) -> bool:
    """Best-effort refresh of the live rules panel message. Returns True if updated."""
    if not conf.get("channel_id") or not conf.get("message_id"):
        return False
    try:
        channel = guild.get_channel(int(conf["channel_id"]))
        if not channel:
            return False
        msg = await channel.fetch_message(int(conf["message_id"]))
        await msg.edit(embeds=build_rules_embeds(guild_id, conf))
        return True
    except (discord.NotFound, discord.Forbidden, AttributeError):
        return False


class RulesMainModal(discord.ui.Modal):
    """Matches the 'Editing: ...' popup — Title / Description / Hex Color, applied to one
    language section of the server rules (Title = language name, Description = rules text)."""

    def __init__(self, guild_id: int, code_upper: str, section: dict | None):
        super().__init__(title=L(guild_id, "rules_modal_title", code=code_upper))
        self.guild_id = guild_id
        self.code_upper = code_upper

        self.title_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_title"),
            required=True,
            max_length=100,
            default=(section.get("name") if section else "") or "",
        )
        self.description_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_description"),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            default=(section.get("content") if section else "") or "",
        )
        self.color_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_color"),
            required=False,
            max_length=7,
            default=(f"{section.get('color'):06X}" if section and section.get("color") else ""),
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = self.guild_id
        code_upper = self.code_upper
        conf = rules_config.get(str(guild_id))
        if not conf:
            await interaction.response.send_message(
                embed=base_embed(L(guild_id, "rules_not_setup_title"), L(guild_id, "rules_not_setup_desc"), color=Theme.DANGER, guild=interaction.guild),
                ephemeral=True,
            )
            return

        sections = conf.setdefault("sections", [])
        existing = get_rules_section(conf, code_upper)
        is_update = existing is not None

        if not is_update and len(sections) >= 10:
            await interaction.response.send_message(
                embed=base_embed(L(guild_id, "rules_too_many_title"), L(guild_id, "rules_too_many_desc", count=len(sections)), color=Theme.WARNING, guild=interaction.guild),
                ephemeral=True,
            )
            return

        color_raw = self.color_input.value.strip().lstrip("#")
        color_value = existing.get("color") if existing else None
        if color_raw:
            try:
                color_value = int(color_raw, 16)
            except ValueError:
                pass
        elif self.color_input.value == "":
            color_value = None

        lang_name = self.title_input.value.strip()
        content = format_rules_content(self.description_input.value.strip())

        section_data = {"code": code_upper, "name": lang_name, "content": content, "color": color_value}
        if is_update:
            existing.update(section_data)
        else:
            sections.append(section_data)
        save_rules_config(rules_config)

        updated_live = await sync_rules_panel(guild_id, interaction.guild, conf)
        note = L(guild_id, "rules_note_live_updated") if updated_live else L(guild_id, "rules_note_live_missing")
        desc_key = "rules_section_updated_desc" if is_update else "rules_section_added_desc"

        section = get_rules_section(conf, code_upper)
        preview = build_single_rules_embed(0, section)
        await interaction.response.send_message(
            content=L(guild_id, desc_key, name=lang_name, code=code_upper, note=note),
            embed=preview,
            view=RulesEditView(guild_id, code_upper),
            ephemeral=True,
        )


class RulesAuthorModal(discord.ui.Modal):
    def __init__(self, guild_id: int, code_upper: str, section: dict):
        super().__init__(title=L(guild_id, "rules_modal_author_title", code=code_upper))
        self.guild_id = guild_id
        self.code_upper = code_upper
        self.name_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_author_name"),
            required=False,
            max_length=256,
            default=section.get("author_name") or "",
        )
        self.icon_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_icon_url"),
            required=False,
            default=section.get("author_icon_url") or "",
        )
        self.add_item(self.name_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = self.guild_id
        conf = rules_config.get(str(guild_id), {})
        section = get_rules_section(conf, self.code_upper)
        if section is None:
            return
        section["author_name"] = self.name_input.value.strip() or None
        section["author_icon_url"] = self.icon_input.value.strip() or None
        save_rules_config(rules_config)
        await sync_rules_panel(guild_id, interaction.guild, conf)

        preview = build_single_rules_embed(0, section)
        await interaction.response.send_message(
            content=L(guild_id, "rules_modal_saved"),
            embed=preview,
            view=RulesEditView(guild_id, self.code_upper),
            ephemeral=True,
        )


class RulesFooterModal(discord.ui.Modal):
    def __init__(self, guild_id: int, code_upper: str, section: dict):
        super().__init__(title=L(guild_id, "rules_modal_footer_title", code=code_upper))
        self.guild_id = guild_id
        self.code_upper = code_upper
        self.text_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_footer_text"),
            required=False,
            max_length=2048,
            default=section.get("footer_text") or "",
        )
        self.icon_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_icon_url"),
            required=False,
            default=section.get("footer_icon_url") or "",
        )
        self.add_item(self.text_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = self.guild_id
        conf = rules_config.get(str(guild_id), {})
        section = get_rules_section(conf, self.code_upper)
        if section is None:
            return
        section["footer_text"] = self.text_input.value.strip() or None
        section["footer_icon_url"] = self.icon_input.value.strip() or None
        save_rules_config(rules_config)
        await sync_rules_panel(guild_id, interaction.guild, conf)

        preview = build_single_rules_embed(0, section)
        await interaction.response.send_message(
            content=L(guild_id, "rules_modal_saved"),
            embed=preview,
            view=RulesEditView(guild_id, self.code_upper),
            ephemeral=True,
        )


class RulesImagesModal(discord.ui.Modal):
    def __init__(self, guild_id: int, code_upper: str, section: dict):
        super().__init__(title=L(guild_id, "rules_modal_images_title", code=code_upper))
        self.guild_id = guild_id
        self.code_upper = code_upper
        self.image_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_image_url"),
            required=False,
            default=section.get("image_url") or "",
        )
        self.thumbnail_input = discord.ui.TextInput(
            label=L(guild_id, "rules_modal_field_thumbnail_url"),
            required=False,
            default=section.get("thumbnail_url") or "",
        )
        self.add_item(self.image_input)
        self.add_item(self.thumbnail_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = self.guild_id
        conf = rules_config.get(str(guild_id), {})
        section = get_rules_section(conf, self.code_upper)
        if section is None:
            return
        section["image_url"] = self.image_input.value.strip() or None
        section["thumbnail_url"] = self.thumbnail_input.value.strip() or None
        save_rules_config(rules_config)
        await sync_rules_panel(guild_id, interaction.guild, conf)

        preview = build_single_rules_embed(0, section)
        await interaction.response.send_message(
            content=L(guild_id, "rules_modal_saved"),
            embed=preview,
            view=RulesEditView(guild_id, self.code_upper),
            ephemeral=True,
        )


class RulesEditView(discord.ui.View):
    """The row of buttons under the modal preview: edit color/description, edit author,
    edit footer, edit images — matches the reference screenshot."""

    def __init__(self, guild_id: int, code_upper: str):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.code_upper = code_upper

    @discord.ui.button(label="edit color / description", style=discord.ButtonStyle.secondary)
    async def edit_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = rules_config.get(str(self.guild_id), {})
        section = get_rules_section(conf, self.code_upper)
        await interaction.response.send_modal(RulesMainModal(self.guild_id, self.code_upper, section))

    @discord.ui.button(label="edit author", style=discord.ButtonStyle.secondary)
    async def edit_author(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = rules_config.get(str(self.guild_id), {})
        section = get_rules_section(conf, self.code_upper) or {}
        await interaction.response.send_modal(RulesAuthorModal(self.guild_id, self.code_upper, section))

    @discord.ui.button(label="edit footer", style=discord.ButtonStyle.secondary)
    async def edit_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = rules_config.get(str(self.guild_id), {})
        section = get_rules_section(conf, self.code_upper) or {}
        await interaction.response.send_modal(RulesFooterModal(self.guild_id, self.code_upper, section))

    @discord.ui.button(label="edit images", style=discord.ButtonStyle.secondary)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        conf = rules_config.get(str(self.guild_id), {})
        section = get_rules_section(conf, self.code_upper) or {}
        await interaction.response.send_modal(RulesImagesModal(self.guild_id, self.code_upper, section))


async def load_custom_emojis():
    try:
        app_emojis = await bot.fetch_application_emojis()
        custom_emoji_cache.clear()
        custom_emoji_cache.update({emoji.name: emoji for emoji in app_emojis})
        logger.info(f"Loaded {len(custom_emoji_cache)} custom emoji(s)")
    except discord.HTTPException:
        logger.exception("Failed to load custom emoji (falling back to unicode emoji)")


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    try:
        await bot.change_presence(status=discord.Status.dnd)
    except Exception:
        logger.exception("Failed to set initial Do Not Disturb presence")

    if not bot.startup_done:
        await load_custom_emojis()
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} slash command(s)")
        except discord.HTTPException:
            logger.exception(
                "Failed to sync commands (may be rate limited) — existing commands still work; will retry on next restart"
            )
        except Exception:
            logger.exception("Unexpected error while syncing commands")
        bot.startup_done = True

    verify_view = VerifyView()
    ticket_open_view = TicketOpenView()
    ticket_close_view = TicketCloseView()

    verify_view.verify_button.emoji = E("star", "⭐")
    ticket_open_view.open_ticket.emoji = E("ticket", "🎫")
    ticket_close_view.close_ticket.emoji = E("lock", "🔒")

    bot.add_view(verify_view)
    bot.add_view(ticket_open_view)
    bot.add_view(ticket_close_view)
    for guild_id_str, conf in scripthub_config.items():
        try:
            bot.add_view(ScriptHubView(int(guild_id_str), conf.get("items", [])))
        except (ValueError, TypeError):
            logger.warning(f"Failed to register scripthub panel for guild {guild_id_str}")

    if not update_status.is_running():
        update_status.start()


@bot.event
async def on_disconnect():
    logger.warning("Disconnected from Discord (discord.py will attempt to reconnect automatically)")


@bot.event
async def on_resumed():
    logger.info("Reconnected to Discord")


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)

    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id
    conf = ai_config.get(str(guild_id))
    if not conf or not conf.get("enabled"):
        return

    bot_mentioned = bot.user in message.mentions
    target_channel_id = conf.get("channel_id")
    in_target_channel = target_channel_id is not None and message.channel.id == int(target_channel_id)

    if not bot_mentioned and not in_target_channel:
        return

    user_text = message.content
    for mention in message.mentions:
        user_text = user_text.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    user_text = user_text.strip()
    if not user_text:
        return

    persona = conf.get("persona") or L(guild_id, "ai_default_persona")

    try:
        async with message.channel.typing():
            reply_text = await generate_ai_reply(
                guild_id, message.channel.id, persona, message.author.display_name, user_text
            )
    except discord.Forbidden:
        return

    for chunk in split_for_discord(reply_text):
        try:
            await message.reply(chunk, mention_author=False)
        except discord.HTTPException:
            logger.exception("Failed to send AI reply")
            break


# =========================================================
# Status rotation (server/member count & time)
# =========================================================
@tasks.loop(seconds=20)
async def update_status():
    try:
        guild_count = len(bot.guilds)
        total_members = sum(g.member_count or 0 for g in bot.guilds)

        now = datetime.datetime.now(timezone(timedelta(hours=7)))
        time_now = now.strftime("%H:%M:%S")
        day_name = now.strftime("%A")

        status_text = (
            f"{guild_count} servers ·⌒ﾞ🍇 {total_members} members ᔕ:･ﾟ🍃 "
            f"{day_name} :･ﾟ☀️ ({time_now})·⌒ﾞ📆"
        )

        activity = discord.Activity(type=discord.ActivityType.watching, name=status_text)
        await bot.change_presence(status=discord.Status.dnd, activity=activity)
    except Exception:
        logger.exception("Error while updating bot status")


@update_status.before_loop
async def before_update_status():
    await bot.wait_until_ready()


@update_status.error
async def update_status_error(error):
    logger.exception(f"update_status loop error: {error}")


@bot.tree.command(name="settings", description="Choose the language the bot uses to reply on this server")
async def settings(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    current_lang_name = AVAILABLE_LANGUAGES[get_guild_language(guild_id)]["name"]
    embed = base_embed(
        L(guild_id, "settings_title"),
        L(guild_id, "settings_desc", current=current_lang_name),
        color=Theme.PRIMARY,
        guild=interaction.guild,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    await interaction.response.send_message(
        embed=embed,
        view=SettingsView(guild_id),
        ephemeral=True,
    )


@bot.tree.command(name="setupverify", description="Set up and send the verification message (button gives a role)")
@app_commands.describe(role="The role to grant when someone verifies")
@app_commands.checks.has_permissions(manage_roles=True)
async def setupverify(interaction: discord.Interaction, role: discord.Role):
    guild_id = interaction.guild.id
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            embed=base_embed(
                L(guild_id, "verify_role_too_high_title"),
                L(guild_id, "verify_role_too_high_desc"),
                color=Theme.DANGER,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )
        return

    verify_config[str(guild_id)] = role.id
    save_verify_config(verify_config)

    embed = base_embed(
        L(guild_id, "verify_panel_title"),
        L(guild_id, "verify_panel_desc", role=role.mention, divider=Theme.DIVIDER),
        color=Theme.PRIMARY,
        guild=interaction.guild,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "verify_setup_success_title"),
            L(guild_id, "verify_setup_sending"),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )
    await interaction.channel.send(embed=embed, view=VerifyView())


def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_messages
    return app_commands.check(predicate)


# =========================================================
# Moderation
# =========================================================

@bot.tree.command(name="clear", description="Delete a number of messages in this channel")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@is_mod()
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    guild_id = interaction.guild.id
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(
        embed=base_embed(
            L(guild_id, "clear_success_title"),
            L(guild_id, "clear_success_desc", count=len(deleted), clap=E("fun_clap", "👏")),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="The member to warn", reason="Reason")
@is_mod()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):
    guild_id = interaction.guild.id
    reason = reason or L(guild_id, "reason_not_specified")
    embed = base_embed(
        L(guild_id, "warn_title"),
        L(guild_id, "warn_desc", member=member.mention, mod=interaction.user.mention),
        color=Theme.WARNING,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=L(guild_id, "warn_reason_field"), value=reason, inline=False)
    await interaction.response.send_message(embed=embed)
    try:
        dm_embed = base_embed(
            L(guild_id, "warn_dm_title"),
            L(guild_id, "warn_dm_desc", guild=interaction.guild.name),
            color=Theme.WARNING,
            guild=interaction.guild,
        ).add_field(name=L(guild_id, "warn_reason_field"), value=reason, inline=False)
        if interaction.guild.icon:
            dm_embed.set_thumbnail(url=interaction.guild.icon.url)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass


@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="The member to kick", reason="Reason")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = None):
    guild_id = interaction.guild.id
    reason = reason or L(guild_id, "reason_not_specified")
    try:
        await member.kick(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed(
                L(guild_id, "kick_no_permission_title"),
                L(guild_id, "kick_no_permission_desc"),
                color=Theme.DANGER,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )
        return
    embed = base_embed(
        L(guild_id, "kick_success_title"),
        L(guild_id, "kick_success_desc", member=member.mention),
        color=Theme.WARNING,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=L(guild_id, "warn_reason_field"), value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="The member to ban", reason="Reason")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = None):
    guild_id = interaction.guild.id
    reason = reason or L(guild_id, "reason_not_specified")
    try:
        await member.ban(reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed(
                L(guild_id, "ban_no_permission_title"),
                L(guild_id, "ban_no_permission_desc"),
                color=Theme.DANGER,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )
        return
    embed = base_embed(
        L(guild_id, "ban_success_title"),
        L(guild_id, "ban_success_desc", member=member.mention),
        color=Theme.DANGER,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=L(guild_id, "warn_reason_field"), value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="timeout", description="Temporarily mute a member")
@app_commands.describe(member="The member", minutes="Duration (minutes)", reason="Reason")
@is_mod()
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10080], reason: str = None):
    guild_id = interaction.guild.id
    reason = reason or L(guild_id, "reason_not_specified")
    duration = datetime.timedelta(minutes=minutes)
    try:
        await member.timeout(duration, reason=reason)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=base_embed(
                L(guild_id, "timeout_no_permission_title"),
                L(guild_id, "timeout_no_permission_desc"),
                color=Theme.DANGER,
                guild=interaction.guild,
            ),
            ephemeral=True,
        )
        return
    embed = base_embed(
        L(guild_id, "timeout_success_title"),
        L(guild_id, "timeout_success_desc", member=member.mention, minutes=minutes),
        color=Theme.WARNING,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=L(guild_id, "warn_reason_field"), value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


# =========================================================
# Role management
# =========================================================

@bot.tree.command(name="addrole", description="Add a role to a member")
@app_commands.describe(member="Member", role="Role to add")
@app_commands.checks.has_permissions(manage_roles=True)
async def addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    guild_id = interaction.guild.id
    await member.add_roles(role)
    embed = base_embed(
        L(guild_id, "addrole_success_title"),
        L(guild_id, "addrole_success_desc", role=role.mention, member=member.mention, thumbsup=E("fun_thumbsup", "👍")),
        color=Theme.SUCCESS,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="removerole", description="Remove a role from a member")
@app_commands.describe(member="Member", role="Role to remove")
@app_commands.checks.has_permissions(manage_roles=True)
async def removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    guild_id = interaction.guild.id
    await member.remove_roles(role)
    embed = base_embed(
        L(guild_id, "removerole_success_title"),
        L(guild_id, "removerole_success_desc", role=role.mention, member=member.mention, ohno=E("fun_ohno", "😅")),
        color=Theme.WARNING,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="nick", description="Change a member's nickname")
@app_commands.describe(member="Member", new_nick="New nickname")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nick(interaction: discord.Interaction, member: discord.Member, new_nick: str):
    guild_id = interaction.guild.id
    await member.edit(nick=new_nick)
    embed = base_embed(
        L(guild_id, "nick_success_title"),
        L(guild_id, "nick_success_desc", member=member.mention, nick=new_nick, laughter=E("fun_laughter", "😂")),
        color=Theme.SUCCESS,
        guild=interaction.guild,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# =========================================================
# Reaction role menu
# =========================================================

@bot.tree.command(name="rolemenu_create", description="Create a reaction role menu message (add options with /rolemenu_add)")
@app_commands.describe(title="Menu title", description="Menu description")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_create(interaction: discord.Interaction, title: str, description: str = "React with an emoji below to get/remove a role"):
    guild_id = interaction.guild.id
    embed = base_embed(f"🎭 {title}", f"{description}\n{Theme.DIVIDER}", color=Theme.PRIMARY, guild=interaction.guild)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    await interaction.response.send_message(
        embed=base_embed(L(guild_id, "rolemenu_created_sending"), None, color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    msg = await interaction.channel.send(embed=embed)

    reactionrole_config.setdefault(str(guild_id), {})[str(msg.id)] = {}
    save_reactionrole_config(reactionrole_config)

    await interaction.edit_original_response(
        content=L(guild_id, "rolemenu_created_note", id=msg.id)
    )


@bot.tree.command(name="rolemenu_add", description="Add an emoji+role option to a role menu")
@app_commands.describe(message_id="Menu message ID (from /rolemenu_create)", emoji="Emoji to use (type or paste)", role="Role to grant on react")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_add(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    guild_id = interaction.guild.id
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rolemenu_role_too_high_title"), L(guild_id, "rolemenu_role_too_high_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    guild_conf = reactionrole_config.get(str(guild_id), {})
    if message_id not in guild_conf:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rolemenu_not_found_title"), L(guild_id, "rolemenu_not_found_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    try:
        target_msg = await interaction.channel.fetch_message(int(message_id))
    except (discord.NotFound, ValueError):
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rolemenu_message_not_found_title"), L(guild_id, "rolemenu_message_not_found_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    try:
        await target_msg.add_reaction(emoji)
    except discord.HTTPException:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rolemenu_bad_emoji_title"), L(guild_id, "rolemenu_bad_emoji_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    guild_conf[message_id][emoji] = role.id
    save_reactionrole_config(reactionrole_config)

    embed = target_msg.embeds[0]
    embed.add_field(name=emoji, value=role.mention, inline=True)
    await target_msg.edit(embed=embed)

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "rolemenu_option_added_title"),
            L(guild_id, "rolemenu_option_added_desc", emoji=emoji, role=role.mention),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="rolemenu_remove", description="Remove an emoji option from a role menu")
@app_commands.describe(message_id="Menu message ID", emoji="Emoji to remove")
@app_commands.checks.has_permissions(manage_roles=True)
async def rolemenu_remove(interaction: discord.Interaction, message_id: str, emoji: str):
    guild_id = interaction.guild.id
    guild_conf = reactionrole_config.get(str(guild_id), {})
    mapping = guild_conf.get(message_id)

    if not mapping or emoji not in mapping:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rolemenu_option_not_found_title"), L(guild_id, "rolemenu_option_not_found_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    del mapping[emoji]
    save_reactionrole_config(reactionrole_config)

    try:
        target_msg = await interaction.channel.fetch_message(int(message_id))
        await target_msg.clear_reaction(emoji)
        embed = target_msg.embeds[0]
        embed.clear_fields()
        for e, rid in mapping.items():
            r = interaction.guild.get_role(rid)
            embed.add_field(name=e, value=r.mention if r else L(guild_id, "rolemenu_role_deleted"), inline=True)
        await target_msg.edit(embed=embed)
    except (discord.NotFound, ValueError, discord.HTTPException):
        pass

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "rolemenu_option_removed_title"),
            L(guild_id, "rolemenu_option_removed_desc", emoji=emoji),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or payload.guild_id is None:
        return

    guild_conf = reactionrole_config.get(str(payload.guild_id))
    if not guild_conf:
        return
    mapping = guild_conf.get(str(payload.message_id))
    if not mapping:
        return

    emoji_str = str(payload.emoji)
    role_id = mapping.get(emoji_str)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return

    try:
        await member.add_roles(role, reason="Got role via reaction menu")
    except discord.Forbidden:
        logger.warning(f"No permission to grant role {role} to {member} via reaction menu")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id or payload.guild_id is None:
        return

    guild_conf = reactionrole_config.get(str(payload.guild_id))
    if not guild_conf:
        return
    mapping = guild_conf.get(str(payload.message_id))
    if not mapping:
        return

    emoji_str = str(payload.emoji)
    role_id = mapping.get(emoji_str)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(role_id)
    if not role:
        return

    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return

    try:
        await member.remove_roles(role, reason="Removed role via reaction menu")
    except discord.Forbidden:
        logger.warning(f"No permission to remove role {role} from {member} via reaction menu")


# =========================================================
# Ticket system — setup commands
# =========================================================

@bot.tree.command(name="setupticket", description="Set up and send the ticket-opening message")
@app_commands.describe(category="The category tickets will be created under", support_role="Support role that can see tickets (optional)")
@app_commands.checks.has_permissions(manage_guild=True)
async def setupticket(interaction: discord.Interaction, category: discord.CategoryChannel, support_role: discord.Role = None):
    guild_id = interaction.guild.id
    ticket_config[str(guild_id)] = {
        "category_id": category.id,
        "support_role_id": support_role.id if support_role else None,
    }
    save_ticket_config(ticket_config)

    embed = base_embed(
        L(guild_id, "ticket_panel_title"),
        L(guild_id, "ticket_panel_desc", divider=Theme.DIVIDER),
        color=Theme.TICKET,
        guild=interaction.guild,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "ticket_setup_success_title"),
            L(guild_id, "ticket_setup_sending"),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )
    await interaction.channel.send(embed=embed, view=TicketOpenView())


@bot.tree.command(name="closeticket", description="Close the current ticket (use inside a ticket channel only)")
async def closeticket(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel = interaction.channel
    conf = ticket_config.get(str(guild_id), {})

    if not channel.topic or "ticket_owner_id:" not in channel.topic:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "ticket_not_a_ticket_title"), L(guild_id, "ticket_not_a_ticket_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    owner_id = int(channel.topic.split("ticket_owner_id:")[1].strip())
    support_role_id = conf.get("support_role_id")
    has_support_role = bool(
        support_role_id and interaction.guild.get_role(int(support_role_id)) in interaction.user.roles
    )
    can_close = owner_id == interaction.user.id or has_support_role or interaction.user.guild_permissions.manage_channels

    if not can_close:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "ticket_no_permission_title"), L(guild_id, "ticket_no_permission_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "ticket_closing_title"),
            L(guild_id, "ticket_closing_desc_simple", member=interaction.user.mention),
            color=Theme.WARNING,
            guild=interaction.guild,
        )
    )
    await discord.utils.sleep_until(datetime.datetime.now(timezone.utc) + timedelta(seconds=5))
    try:
        await channel.delete(reason=f"Ticket closed by {interaction.user}")
    except discord.NotFound:
        pass


# =========================================================
# Script/File hub panel — commands
# =========================================================

@bot.tree.command(name="scripthub_setup", description="Create/update the file-sharing panel (has a dropdown menu)")
@app_commands.describe(
    title="Panel title, e.g. SCRIPT HUB PANEL",
    description="Description shown under the title",
    image_url="Image URL (optional)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_setup(
    interaction: discord.Interaction, title: str, description: str, image_url: str = None
):
    guild_id = interaction.guild.id
    conf = scripthub_config.get(str(guild_id), {"items": []})
    conf["title"] = title
    conf["description"] = description
    conf["image_url"] = image_url

    embed = build_scripthub_embed(guild_id, conf)
    view = ScriptHubView(guild_id, conf.get("items", []))

    await interaction.response.send_message(
        embed=base_embed(L(guild_id, "scripthub_creating_title"), L(guild_id, "scripthub_creating_desc"), color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    msg = await interaction.channel.send(embed=embed, view=view)

    conf["channel_id"] = interaction.channel.id
    conf["message_id"] = msg.id
    scripthub_config[str(guild_id)] = conf
    save_scripthub_config(scripthub_config)

    await interaction.edit_original_response(content=L(guild_id, "scripthub_setup_done"))


@bot.tree.command(name="scripthub_additem", description="Add a file/template item to the panel (attach a file, or use a text message)")
@app_commands.describe(
    label="Item name shown in the menu (short, max 100 chars)",
    description="Short description of the item (shown in the menu)",
    content="Text to include with the DM (optional if a file is attached)",
    file="File to send to the user (optional if only text is used)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_additem(
    interaction: discord.Interaction,
    label: str,
    description: str = "",
    content: str = None,
    file: discord.Attachment = None,
):
    guild_id = interaction.guild.id
    if not content and not file:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_missing_data_title"), L(guild_id, "scripthub_missing_data_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    conf = scripthub_config.get(str(guild_id))
    if not conf:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_not_setup_title"), L(guild_id, "scripthub_not_setup_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items = conf.setdefault("items", [])
    if any(i["label"] == label for i in items):
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_duplicate_title"), L(guild_id, "scripthub_duplicate_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return
    if len(items) >= 25:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_full_title"), L(guild_id, "scripthub_full_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    file_path = None
    file_name = None
    if file:
        guild_dir = os.path.join(SCRIPTHUB_FILES_DIR, str(guild_id))
        os.makedirs(guild_dir, exist_ok=True)
        safe_label = safe_filename_part(label, fallback="item")
        safe_name = safe_filename_part(file.filename, fallback="file")
        file_path = os.path.join(guild_dir, f"{safe_label}_{safe_name}")
        await file.save(file_path)
        file_name = file.filename

    items.append(
        {
            "label": label,
            "description": description,
            "content": content,
            "file_path": file_path,
            "file_name": file_name,
        }
    )
    save_scripthub_config(scripthub_config)

    updated_live = False
    if conf.get("channel_id") and conf.get("message_id"):
        try:
            channel = interaction.guild.get_channel(int(conf["channel_id"]))
            msg = await channel.fetch_message(int(conf["message_id"]))
            await msg.edit(embed=build_scripthub_embed(guild_id, conf), view=ScriptHubView(guild_id, items))
            updated_live = True
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

    note = L(guild_id, "scripthub_note_updated") if updated_live else L(guild_id, "scripthub_note_not_found")
    await interaction.followup.send(
        embed=base_embed(
            L(guild_id, "scripthub_item_added_title"),
            L(guild_id, "scripthub_item_added_desc", label=label, note=note),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="scripthub_removeitem", description="Remove a file/template item from the panel")
@app_commands.describe(label="Name of the item to remove")
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_removeitem(interaction: discord.Interaction, label: str):
    guild_id = interaction.guild.id
    conf = scripthub_config.get(str(guild_id))
    if not conf or not conf.get("items"):
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_no_items_title"), L(guild_id, "scripthub_no_items_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items = conf["items"]
    target = next((i for i in items if i["label"] == label), None)
    if not target:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_item_not_found_title"), L(guild_id, "scripthub_item_not_found_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    items.remove(target)
    if target.get("file_path") and os.path.exists(target["file_path"]):
        try:
            os.remove(target["file_path"])
        except OSError:
            pass
    save_scripthub_config(scripthub_config)

    updated_live = False
    if conf.get("channel_id") and conf.get("message_id"):
        try:
            channel = interaction.guild.get_channel(int(conf["channel_id"]))
            msg = await channel.fetch_message(int(conf["message_id"]))
            await msg.edit(embed=build_scripthub_embed(guild_id, conf), view=ScriptHubView(guild_id, items))
            updated_live = True
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

    note = L(guild_id, "scripthub_note_removed_updated") if updated_live else L(guild_id, "scripthub_note_removed_not_found")
    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "scripthub_removed_title"),
            L(guild_id, "scripthub_removed_desc", label=label, note=note),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="scripthub_listitems", description="List all file/template items in this server's panel")
@app_commands.checks.has_permissions(manage_guild=True)
async def scripthub_listitems(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    conf = scripthub_config.get(str(guild_id))
    items = conf.get("items", []) if conf else []

    if not items:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "scripthub_empty_list_title"), L(guild_id, "scripthub_empty_list_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    lines = []
    for i in items:
        kind = L(guild_id, "scripthub_kind_file") if i.get("file_path") else L(guild_id, "scripthub_kind_text")
        lines.append(f"**• {i['label']}** — {i.get('description') or '-'}  `{kind}`")

    embed = base_embed(
        L(guild_id, "scripthub_list_title"),
        "\n".join(lines),
        color=Theme.SCRIPTHUB,
        guild=interaction.guild,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# Server rules panel (multi-language)
# =========================================================

@bot.tree.command(name="rules_setup", description="Create/send the server rules panel in this channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def rules_setup(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    conf = rules_config.get(str(guild_id), {"sections": []})

    embeds = build_rules_embeds(guild_id, conf)

    await interaction.response.send_message(
        embed=base_embed(L(guild_id, "rules_setup_success_title"), L(guild_id, "rules_setup_sending"), color=Theme.SUCCESS, guild=interaction.guild),
        ephemeral=True,
    )
    msg = await interaction.channel.send(embeds=embeds)

    conf["channel_id"] = interaction.channel.id
    conf["message_id"] = msg.id
    rules_config[str(guild_id)] = conf
    save_rules_config(rules_config)

    note = "" if conf.get("sections") else f"\n{L(guild_id, 'rules_setup_empty_note')}"
    await interaction.edit_original_response(content=f"✅{note}")


@bot.tree.command(name="rules_edit", description="Open the rules editor for a language section (title/description/color, + author/footer/images)")
@app_commands.describe(lang_code="Short code for this language, e.g. EN, RU, TH (creates it if it doesn't exist yet)")
@app_commands.checks.has_permissions(manage_guild=True)
async def rules_edit(interaction: discord.Interaction, lang_code: str):
    guild_id = interaction.guild.id
    conf = rules_config.get(str(guild_id))
    if not conf:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rules_not_setup_title"), L(guild_id, "rules_not_setup_desc"), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    code_upper = lang_code.strip().upper()
    section = get_rules_section(conf, code_upper)
    await interaction.response.send_modal(RulesMainModal(guild_id, code_upper, section))


@bot.tree.command(name="rules_removesection", description="Remove a language section from the rules panel")
@app_commands.describe(lang_code="The language code to remove, e.g. EN")
@app_commands.checks.has_permissions(manage_guild=True)
async def rules_removesection(interaction: discord.Interaction, lang_code: str):
    guild_id = interaction.guild.id
    conf = rules_config.get(str(guild_id))
    code_upper = lang_code.strip().upper()
    sections = conf.get("sections", []) if conf else []
    target = next((s for s in sections if s["code"] == code_upper), None)

    if not target:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rules_section_not_found_title"), L(guild_id, "rules_section_not_found_desc", code=code_upper), color=Theme.DANGER, guild=interaction.guild),
            ephemeral=True,
        )
        return

    sections.remove(target)
    save_rules_config(rules_config)

    updated_live = False
    if conf.get("channel_id") and conf.get("message_id"):
        try:
            channel = interaction.guild.get_channel(int(conf["channel_id"]))
            msg = await channel.fetch_message(int(conf["message_id"]))
            await msg.edit(embeds=build_rules_embeds(guild_id, conf))
            updated_live = True
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

    note = L(guild_id, "rules_note_live_updated") if updated_live else L(guild_id, "rules_note_live_missing")
    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "rules_section_removed_title"),
            L(guild_id, "rules_section_removed_desc", code=code_upper, note=note),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="rules_listsections", description="List all language sections in the rules panel")
@app_commands.checks.has_permissions(manage_guild=True)
async def rules_listsections(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    conf = rules_config.get(str(guild_id))
    sections = conf.get("sections", []) if conf else []

    if not sections:
        await interaction.response.send_message(
            embed=base_embed(L(guild_id, "rules_no_sections_title"), L(guild_id, "rules_no_sections_desc"), color=Theme.WARNING, guild=interaction.guild),
            ephemeral=True,
        )
        return

    lines = [f"**[{s['code']}]** {s['name']}" for s in sections]
    embed = base_embed(L(guild_id, "rules_list_title"), "\n".join(lines), color=Theme.PRIMARY, guild=interaction.guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# AI chat system (Groq)
# =========================================================

@bot.tree.command(name="ai_setup", description="Set up the AI chat system for this server")
@app_commands.describe(channel="Channel where the AI replies to every message (leave empty = only reply when @mentioned)")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_setup(interaction: discord.Interaction, channel: discord.TextChannel = None):
    guild_id = interaction.guild.id
    conf = ai_config.get(str(guild_id), {"enabled": True, "channel_id": None, "persona": None})
    conf["enabled"] = True
    conf["channel_id"] = channel.id if channel else None
    ai_config[str(guild_id)] = conf
    save_ai_config(ai_config)

    where = L(guild_id, "ai_setup_where_channel", channel=channel.mention) if channel else L(guild_id, "ai_setup_where_mention")
    embed = base_embed(
        L(guild_id, "ai_setup_success_title"),
        L(guild_id, "ai_setup_success_desc", where=where),
        color=Theme.SUCCESS,
        guild=interaction.guild,
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ai_toggle", description="Turn the AI chat system on or off for this server")
@app_commands.describe(enabled="On (True) or off (False)")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_toggle(interaction: discord.Interaction, enabled: bool):
    guild_id = interaction.guild.id
    conf = ai_config.get(str(guild_id), {"enabled": True, "channel_id": None, "persona": None})
    conf["enabled"] = enabled
    ai_config[str(guild_id)] = conf
    save_ai_config(ai_config)

    status_text = L(guild_id, "ai_toggle_on") if enabled else L(guild_id, "ai_toggle_off")
    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "ai_toggle_updated_title"),
            L(guild_id, "ai_toggle_updated_desc", status=status_text),
            color=Theme.SUCCESS if enabled else Theme.WARNING,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="ai_persona", description="Set the AI's persona / base rules (system prompt)")
@app_commands.describe(persona="Description of the persona/rules the AI should follow")
@app_commands.checks.has_permissions(manage_guild=True)
async def ai_persona(interaction: discord.Interaction, persona: str):
    guild_id = interaction.guild.id
    conf = ai_config.get(str(guild_id), {"enabled": True, "channel_id": None, "persona": None})
    conf["persona"] = persona
    ai_config[str(guild_id)] = conf
    save_ai_config(ai_config)

    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "ai_persona_success_title"),
            L(guild_id, "ai_persona_success_desc"),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


@bot.tree.command(name="ai_reset", description="Clear this channel's AI conversation memory")
@app_commands.checks.has_permissions(manage_messages=True)
async def ai_reset(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    ai_conversations.pop(interaction.channel.id, None)
    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "ai_reset_success_title"),
            L(guild_id, "ai_reset_success_desc"),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )


# =========================================================
# General commands
# =========================================================

@bot.tree.command(name="ping", description="Check the bot's latency")
async def ping(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    latency_ms = round(bot.latency * 1000)
    if latency_ms < 150:
        color, mood = Theme.SUCCESS, E("fun_perfect", "😎")
    elif latency_ms < 300:
        color, mood = Theme.WARNING, E("fun_ok", "😐")
    else:
        color, mood = Theme.DANGER, E("fun_nervous", "😬")
    embed = base_embed(L(guild_id, "ping_pong_title"), L(guild_id, "ping_pong_desc", ms=latency_ms, mood=mood), color=color, guild=interaction.guild)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="View a member's info")
@app_commands.describe(member="Member to look up (leave empty = yourself)")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    guild_id = interaction.guild.id
    member = member or interaction.user
    embed = base_embed(L(guild_id, "userinfo_title", member=member.display_name), color=Theme.INFO, guild=interaction.guild)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name=L(guild_id, "userinfo_username_field"), value=str(member), inline=True)
    embed.add_field(name=L(guild_id, "userinfo_id_field"), value=f"`{member.id}`", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name=L(guild_id, "userinfo_joined_field"), value=member.joined_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name=L(guild_id, "userinfo_created_field"), value=member.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed.add_field(name=L(guild_id, "userinfo_roles_field", count=len(roles)), value=", ".join(roles) if roles else L(guild_id, "userinfo_no_roles"), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="View server info")
async def serverinfo(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    guild = interaction.guild
    embed = base_embed(f"🏰 {guild.name}", color=Theme.PRIMARY, guild=guild)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    embed.add_field(name=L(guild_id, "serverinfo_owner_field"), value=guild.owner.mention if guild.owner else "-", inline=True)
    embed.add_field(name=L(guild_id, "serverinfo_members_field"), value=f"{guild.member_count:,}", inline=True)
    embed.add_field(name=L(guild_id, "serverinfo_boosts_field"), value=f"Level {guild.premium_tier} ({guild.premium_subscription_count})", inline=True)
    embed.add_field(name=L(guild_id, "serverinfo_created_field"), value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name=L(guild_id, "serverinfo_channels_field"), value=len(guild.channels), inline=True)
    embed.add_field(name=L(guild_id, "serverinfo_roles_field"), value=len(guild.roles), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="poll", description="Create a simple poll (👍/👎 vote)")
@app_commands.describe(question="The poll question")
async def poll(interaction: discord.Interaction, question: str):
    guild_id = interaction.guild.id
    embed = base_embed(
        L(guild_id, "poll_title"),
        L(guild_id, "poll_desc", question=question, divider=Theme.DIVIDER, gamer=E("fun_gamer", "🎮")),
        color=Theme.INFO,
        guild=interaction.guild,
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


@bot.tree.command(name="say", description="Have the bot say something on your behalf")
@app_commands.describe(message="The message for the bot to say")
@is_mod()
async def say(interaction: discord.Interaction, message: str):
    guild_id = interaction.guild.id
    await interaction.response.send_message(
        embed=base_embed(
            L(guild_id, "say_sent_title"),
            L(guild_id, "say_sent_desc", wink=E("fun_wink", "😉")),
            color=Theme.SUCCESS,
            guild=interaction.guild,
        ),
        ephemeral=True,
    )
    await interaction.channel.send(message)


@bot.tree.command(name="user", description="View a user's Roblox/Rolimon's stats (RAP, Value, Collectibles, Value Rank)")
@app_commands.describe(username="Roblox username or User ID")
async def user_lookup(interaction: discord.Interaction, username: str):
    guild_id = interaction.guild.id
    await interaction.response.defer()

    roblox_user = await resolve_roblox_user(username)
    if not roblox_user:
        await interaction.followup.send(
            embed=base_embed(
                L(guild_id, "user_lookup_not_found_title"),
                L(guild_id, "user_lookup_not_found_desc", username=username),
                color=Theme.DANGER,
                guild=interaction.guild,
            )
        )
        return

    user_id = roblox_user["id"]
    display_name = roblox_user["display_name"]
    real_name = roblox_user["name"]

    player_info, collectibles, avatar_url = await asyncio.gather(
        fetch_rolimons_playerinfo(user_id),
        fetch_rolimons_collectibles(user_id),
        fetch_roblox_avatar(user_id),
    )

    if not player_info:
        await interaction.followup.send(
            embed=base_embed(
                L(guild_id, "user_lookup_failed_title"),
                L(guild_id, "user_lookup_failed_desc", name=display_name),
                color=Theme.WARNING,
                guild=interaction.guild,
            )
        )
        return

    rap = player_info.get("rap", 0) or 0
    value = player_info.get("value", 0) or 0
    rank = player_info.get("rank")
    rank_text = f"#{rank:,}" if rank else L(guild_id, "user_lookup_no_data")
    collectibles_text = f"{collectibles:,}" if collectibles is not None else L(guild_id, "user_lookup_no_data")

    embed = discord.Embed(color=Theme.ROLIMONS, timestamp=datetime.datetime.now(timezone.utc))
    embed.set_author(
        name="Rolimon's",
        icon_url="https://www.rolimons.com/favicon.ico",
        url=f"https://www.rolimons.com/player/{user_id}",
    )
    embed.title = "Roblox"
    name_line = f"**{display_name}**"
    if real_name != display_name:
        name_line += f" (@{real_name})"
    embed.description = name_line
    embed.add_field(name="RAP", value=f"{rap:,}", inline=True)
    embed.add_field(name="Value", value=f"{value:,}", inline=True)
    embed.add_field(name="Collectibles", value=collectibles_text, inline=True)
    embed.add_field(name="Value Rank", value=rank_text, inline=False)
    embed.set_footer(text=L(guild_id, "user_lookup_footer"))
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    await interaction.followup.send(embed=embed, view=RolimonsProfileView(user_id))


@bot.tree.command(name="help", description="Show all available commands")
async def help_command(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    embed = base_embed(
        L(guild_id, "help_title"),
        f"{L(guild_id, 'help_desc')}\n{Theme.DIVIDER}",
        color=Theme.PRIMARY,
        guild=interaction.guild,
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name=L(guild_id, "help_moderation"), value="`/clear` `/warn` `/kick` `/ban` `/timeout`", inline=False)
    embed.add_field(name=L(guild_id, "help_roles"), value="`/addrole` `/removerole` `/nick`", inline=False)
    embed.add_field(name=L(guild_id, "help_general"), value="`/ping` `/userinfo` `/serverinfo` `/poll` `/say`", inline=False)
    embed.add_field(name=L(guild_id, "help_roblox"), value=L(guild_id, "help_roblox_desc"), inline=False)
    embed.add_field(name=L(guild_id, "help_verify"), value=L(guild_id, "help_verify_desc"), inline=False)
    embed.add_field(
        name=L(guild_id, "help_rolemenu"),
        value="`/rolemenu_create`\n`/rolemenu_add`\n`/rolemenu_remove`",
        inline=False,
    )
    embed.add_field(
        name=L(guild_id, "help_ticket"),
        value="`/setupticket`\n`/closeticket`",
        inline=False,
    )
    embed.add_field(
        name=L(guild_id, "help_scripthub"),
        value="`/scripthub_setup`\n`/scripthub_additem`\n`/scripthub_removeitem`\n`/scripthub_listitems`",
        inline=False,
    )
    embed.add_field(
        name=L(guild_id, "help_ai"),
        value="`/ai_setup`\n`/ai_toggle`\n`/ai_persona`\n`/ai_reset`",
        inline=False,
    )
    embed.add_field(
        name=L(guild_id, "help_rules"),
        value="`/rules_setup`\n`/rules_edit`\n`/rules_removesection`\n`/rules_listsections`",
        inline=False,
    )
    embed.add_field(name=L(guild_id, "help_settings"), value=L(guild_id, "help_settings_desc"), inline=False)
    await interaction.response.send_message(embed=embed)


# =========================================================
# Error handling
# =========================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    guild_id = interaction.guild.id if interaction.guild else None

    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        msg = L(guild_id, "error_no_permission") if guild_id else "❌ You don't have permission to use this command"
        title = None
    else:
        msg = L(guild_id, "error_generic_desc") if guild_id else "❌ An error occurred while running this command. Please try again"
        title = L(guild_id, "error_generic_title") if guild_id else "Something went wrong"
        logger.exception(f"Unhandled app command error: {error}")

    embed = base_embed(title or "❌", msg, color=Theme.DANGER, guild=interaction.guild if interaction.guild else None)

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        logger.error(
            "BOT_TOKEN not found — please create a .env file (see .env.example) "
            "and set BOT_TOKEN=your_token before running the bot."
        )
    else:
        start_keep_alive()
        try:
            bot.run(TOKEN, log_handler=None)
        except discord.LoginFailure:
            logger.error("Invalid token — please check BOT_TOKEN in .env")
        except Exception:
            logger.exception("Bot stopped due to an unexpected error")
