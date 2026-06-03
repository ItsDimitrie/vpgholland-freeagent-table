import os
import csv
import json
import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("leaderboard-bot")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
MESSAGE_ID = int(os.getenv("MESSAGE_ID", "0"))

EMBED_TITLE = os.getenv("EMBED_TITLE", "VPG Holland Free Agents")
BUTTON_LABEL = os.getenv("BUTTON_LABEL", "Bewerk je Free Agent rol")
CSV_PATH = os.getenv("CSV_PATH", "data.csv")
MESSAGES_FILE = "message_ids.json"

POSITION_ROLE_IDS = [
    int(x.strip())
    for x in os.getenv("POSITION_ROLE_IDS", "").split(",")
    if x.strip().isdigit()
]

POSITION_ROLE_NAMES = [
    x.strip()
    for x in os.getenv("POSITION_ROLE_NAMES", "").split(",")
    if x.strip()
]

EMBED_COLOR = discord.Color.from_rgb(255, 140, 0)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

LAST_REFRESH_TIME = None
refresh_lock = asyncio.Lock()


def footer_text():

    if LAST_REFRESH_TIME is None:
        return "Refreshed elke 5 minuten"

    return (
        "Refreshed elke 5 minuten • " + "© VPG Holland 2026 • " + "Vragen? Stel ze via de @staflid rol! • "
        f" • Last refresh: {LAST_REFRESH_TIME.strftime('%H:%M:%S UTC')}"
    )


def load_message_ids():
    try:
        with open(MESSAGES_FILE) as f:
            ids = json.load(f)
            if isinstance(ids, list) and ids:
                return ids
    except Exception:
        pass
    if MESSAGE_ID:
        return [MESSAGE_ID]
    return []


def save_message_ids(ids):
    try:
        with open(MESSAGES_FILE, "w") as f:
            json.dump(ids, f)
    except Exception:
        log.exception("Failed to save message IDs")


def export_members_csv(members):

    try:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "display_name"])

            for member in members:

                writer.writerow([
                    member.id,
                    member.name,
                    member.display_name
                ])

    except Exception:
        log.exception("Failed to export CSV")


def get_position_roles(guild):

    result = []

    for index, role_id in enumerate(POSITION_ROLE_IDS):

        role = guild.get_role(role_id)

        if role is None:
            continue

        label = (
            POSITION_ROLE_NAMES[index]
            if index < len(POSITION_ROLE_NAMES)
            else role.name
        )

        result.append((role, label))

    return result


def format_member_line(member):

    return (
        f"{member.display_name}"
        f" - @{member.name}"
        f" - {member.mention}"
    )


def embed_char_count(embed):
    total = len(embed.title or "")
    for field in embed.fields:
        total += len(field.name) + len(field.value)
    return total


def split_text(text, limit=1024):

    if len(text) <= limit:
        return [text]

    lines = text.split("\n")

    chunks = []
    current = ""

    for line in lines:

        candidate = f"{current}\n{line}".strip()

        if len(candidate) > limit:

            if current:
                chunks.append(current)

            current = line

        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


async def build_embeds(guild):

    free_agent_role = guild.get_role(ROLE_ID)

    free_agents = sorted(
        [m for m in free_agent_role.members if not m.bot],
        key=lambda m: m.display_name.lower()
    )

    export_members_csv(free_agents)

    footer = footer_text()

    position_roles = get_position_roles(guild)

    grouped_fields = []

    assigned_ids = set()

    for role, label in position_roles:

        role_members = [
            member for member in free_agents
            if role in member.roles
        ]

        role_members.sort(
            key=lambda m: m.display_name.lower()
        )

        for member in role_members:
            assigned_ids.add(member.id)

        if role_members:

            lines = [
                format_member_line(member)
                for member in role_members
            ]

            value = "\n".join(lines)

        else:

            value = "*No players*"

        parts = split_text(value)

        header_name = f"{label}"

        for idx, part in enumerate(parts, start=1):

            field_name = (
                header_name
                if idx == 1
                else f"{label} (cont.)"
            )

            grouped_fields.append(
                (field_name, part)
            )

        grouped_fields.append(
            ("──────────────", "​")
        )

    no_position = [
        member for member in free_agents
        if member.id not in assigned_ids
    ]

    if no_position:

        lines = [
            format_member_line(member)
            for member in no_position
        ]

        value = "\n".join(lines)

        parts = split_text(value)

        for idx, part in enumerate(parts, start=1):

            field_name = (
                "Geen positie aangegeven"
                if idx == 1
                else "Geen positie aangegeven (cont.)"
            )

            grouped_fields.append(
                (field_name, part)
            )

    embeds = []

    current_embed = discord.Embed(
        title=EMBED_TITLE,
        color=EMBED_COLOR
    )

    if guild.icon:
        current_embed.set_thumbnail(
            url=guild.icon.url
        )

    current_embed.add_field(
        name="Aantal Free Agents",
        value=str(len(free_agents)),
        inline=True
    )

    field_count = 1

    for name, value in grouped_fields:

        field_chars = len(name) + len(value)
        # Each embed is sent as its own message so the 6000-char cap is per embed.
        # Keep a 200-char buffer for the footer that gets appended on close.
        would_exceed = embed_char_count(current_embed) + len(footer) + field_chars > 5800

        if field_count >= 25 or would_exceed:

            current_embed.set_footer(text=footer)
            embeds.append(current_embed)

            current_embed = discord.Embed(
                title=f"{EMBED_TITLE} (cont.)",
                color=EMBED_COLOR
            )

            if guild.icon:
                current_embed.set_thumbnail(url=guild.icon.url)

            current_embed.add_field(
                name="Total members",
                value=str(len(free_agents)),
                inline=True
            )

            field_count = 1

        current_embed.add_field(
            name=name,
            value=value,
            inline=False
        )

        field_count += 1

    current_embed.set_footer(text=footer)
    embeds.append(current_embed)

    return embeds


class RoleToggleView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label=BUTTON_LABEL,
        style=discord.ButtonStyle.danger,
        custom_id="persistent_role_toggle_button"
    )
    async def toggle_role(
        self,
        interaction,
        button
    ):

        guild = interaction.guild

        role = guild.get_role(
            ROLE_ID
        )

        member = interaction.user

        if role in member.roles:

            await member.remove_roles(
                role
            )

            action = "removed from"

        else:

            await member.add_roles(
                role
            )

            action = "added to"

        await interaction.response.send_message(
            f"You were {action} {role.mention}.",
            ephemeral=True
        )

        await refresh_leaderboard_message(
            guild
        )


async def get_target_channel(guild):

    channel = guild.get_channel(
        CHANNEL_ID
    )

    if channel is None:

        channel = await bot.fetch_channel(
            CHANNEL_ID
        )

    return channel


async def find_leaderboard_messages(channel):
    """Scan channel history for messages posted by this bot with leaderboard embeds."""
    found = []
    async for msg in channel.history(limit=100):
        if msg.author.id == bot.user.id and msg.embeds:
            title = msg.embeds[0].title or ""
            if EMBED_TITLE in title:
                found.append(msg)
    found.sort(key=lambda m: m.created_at)
    return found


async def fetch_stored_messages(channel):
    """Return existing leaderboard messages, falling back to a channel scan."""
    stored_ids = load_message_ids()
    existing = []
    for mid in stored_ids:
        try:
            existing.append(await channel.fetch_message(mid))
        except Exception:
            pass

    if not existing:
        existing = await find_leaderboard_messages(channel)
        if existing:
            save_message_ids([m.id for m in existing])
            log.info("Recovered %d leaderboard message(s) from channel history", len(existing))

    return existing


async def refresh_leaderboard_message(guild):
    """Send one Discord message per embed so we never hit the 6000-char per-message limit."""

    global LAST_REFRESH_TIME

    async with refresh_lock:

        LAST_REFRESH_TIME = datetime.now(timezone.utc)

        channel = await get_target_channel(guild)
        embeds = await build_embeds(guild)
        existing = await fetch_stored_messages(channel)

        new_ids = []

        # Edit existing messages or send new ones.
        for i, embed in enumerate(embeds):
            view = RoleToggleView() if i == 0 else None
            mentions = discord.AllowedMentions(roles=True, users=True)

            if i < len(existing):
                await existing[i].edit(
                    embed=embed,
                    view=view,
                    allowed_mentions=mentions
                )
                new_ids.append(existing[i].id)
            else:
                msg = await channel.send(
                    embed=embed,
                    view=view,
                    allowed_mentions=mentions
                )
                new_ids.append(msg.id)
                log.info("Sent new leaderboard message ID %s", msg.id)

        # Delete surplus messages left over from previous runs with more pages.
        for msg in existing[len(embeds):]:
            try:
                await msg.delete()
            except Exception:
                pass

        save_message_ids(new_ids)


@tasks.loop(minutes=5)
async def periodic_refresh():

    guild = bot.get_guild(
        GUILD_ID
    )

    if guild:

        await refresh_leaderboard_message(
            guild
        )


async def cleanup_duplicate_messages(channel):
    """Delete duplicate leaderboard messages, keeping only the oldest run."""
    all_msgs = []
    async for msg in channel.history(limit=100):
        if msg.author.id == bot.user.id and msg.embeds:
            title = msg.embeds[0].title or ""
            if EMBED_TITLE in title:
                all_msgs.append(msg)

    if not all_msgs:
        return

    all_msgs.sort(key=lambda m: m.created_at)

    # Identify contiguous "runs" of bot messages (grouped by proximity in time).
    runs = [[all_msgs[0]]]
    for msg in all_msgs[1:]:
        gap = (msg.created_at - runs[-1][-1].created_at).total_seconds()
        if gap < 30:
            runs[-1].append(msg)
        else:
            runs.append([msg])

    if len(runs) <= 1:
        return

    log.warning("Found %d duplicate leaderboard run(s), cleaning up", len(runs) - 1)

    # Keep the most recent run, delete all older ones.
    for run in runs[:-1]:
        for msg in run:
            try:
                await msg.delete()
            except Exception:
                pass

    # Save IDs of the surviving run.
    save_message_ids([m.id for m in runs[-1]])


@bot.event
async def on_ready():

    log.info(
        "Logged in as %s",
        bot.user
    )

    bot.add_view(
        RoleToggleView()
    )

    await tree.sync(
        guild=discord.Object(
            id=GUILD_ID
        )
    )

    if not periodic_refresh.is_running():

        periodic_refresh.start()

    guild = bot.get_guild(
        GUILD_ID
    )

    if guild:

        channel = await get_target_channel(guild)
        await cleanup_duplicate_messages(channel)
        await refresh_leaderboard_message(
            guild
        )


@bot.event
async def on_member_update(
    before,
    after
):

    relevant_role_ids = set(
        POSITION_ROLE_IDS
        + [ROLE_ID]
    )

    before_ids = {
        role.id
        for role in before.roles
    }

    after_ids = {
        role.id
        for role in after.roles
    }

    if (
        before_ids
        & relevant_role_ids
    ) != (
        after_ids
        & relevant_role_ids
    ):

        await refresh_leaderboard_message(
            after.guild
        )


bot.run(TOKEN)
