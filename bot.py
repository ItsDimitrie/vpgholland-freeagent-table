import os
import csv
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
        return "Auto-refreshes every 5 minutes"

    return (
        "Auto-refreshes every 5 minutes"
        f" • Last refresh: {LAST_REFRESH_TIME.strftime('%H:%M:%S UTC')}"
    )


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
            ("──────────────", "\u200b")
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

        if field_count >= 25:

            current_embed.set_footer(
                text=footer
            )

            embeds.append(
                current_embed
            )

            current_embed = discord.Embed(
                title=f"{EMBED_TITLE} (cont.)",
                color=EMBED_COLOR
            )

            if guild.icon:
                current_embed.set_thumbnail(
                url=guild.icon.url
            )

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

    current_embed.set_footer(
        text=footer
    )

    embeds.append(
        current_embed
    )

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


async def get_or_create_leaderboard_message(guild):

    global MESSAGE_ID

    channel = await get_target_channel(
        guild
    )

    if MESSAGE_ID:

        try:

            return await channel.fetch_message(
                MESSAGE_ID
            )

        except Exception:

            pass

    embeds = await build_embeds(
        guild
    )

    message = await channel.send(
        embeds=embeds,
        view=RoleToggleView(),
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=True
        )
    )

    MESSAGE_ID = message.id

    log.warning(
        "Created message ID %s",
        MESSAGE_ID
    )

    return message


async def refresh_leaderboard_message(guild):

    global LAST_REFRESH_TIME

    async with refresh_lock:

        LAST_REFRESH_TIME = datetime.now(
            timezone.utc
        )

        message = await get_or_create_leaderboard_message(
            guild
        )

        embeds = await build_embeds(
            guild
        )

    await message.edit(
        embeds=embeds,
        view=RoleToggleView(),
        allowed_mentions=discord.AllowedMentions(
            roles=True,
            users=True
        )
    )


@tasks.loop(minutes=5)
async def periodic_refresh():

    guild = bot.get_guild(
        GUILD_ID
    )

    if guild:

        await refresh_leaderboard_message(
            guild
        )


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