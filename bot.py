import os
import csv
import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
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
MESSAGE_ID = int(os.getenv("MESSAGE_ID", "0"))  # optional; bot can create one if missing
EMBED_TITLE = os.getenv("EMBED_TITLE", "VPG Holland Free Agents")
BUTTON_LABEL = os.getenv("BUTTON_LABEL", "Toggle Role")
CSV_PATH = os.getenv("CSV_PATH", "data.csv")

if not TOKEN:
    raise ValueError("Missing DISCORD_TOKEN in environment variables")
if not GUILD_ID or not ROLE_ID or not CHANNEL_ID:
    raise ValueError("Missing GUILD_ID, ROLE_ID, or CHANNEL_ID in environment variables")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # required to read role members reliably

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def chunk_lines(lines: list[str], max_chars: int = 3900) -> list[str]:
    chunks = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if len(candidate) > max_chars:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks or ["No users currently have this role."]


def export_members_csv(role: discord.Role) -> None:
    """
    Debug/export only.
    On Railway this file should be treated as temporary and non-persistent.
    """
    try:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "display_name"])
            for member in sorted(role.members, key=lambda m: m.display_name.lower()):
                writer.writerow([member.id, str(member), member.display_name])
    except Exception:
        log.exception("Failed to export CSV")


async def build_embeds(guild: discord.Guild) -> list[discord.Embed]:
    role = guild.get_role(ROLE_ID)
    if role is None:
        raise RuntimeError(f"Role {ROLE_ID} not found")

    members = sorted(
        [m for m in role.members if not m.bot],
        key=lambda m: m.display_name.lower()
    )

    export_members_csv(role)

    if not members:
        embed = discord.Embed(
            title=EMBED_TITLE,
            description=f"No users currently have {role.mention}.",
        )
        embed.set_footer(text="Press the button below to add or remove the role.")
        return [embed]

    lines = [f"• {member.mention} — {discord.utils.escape_markdown(member.display_name)}" for member in members]
    chunks = chunk_lines(lines)

    embeds = []
    total = len(chunks)

    for index, chunk in enumerate(chunks, start=1):
        title = EMBED_TITLE if total == 1 else f"{EMBED_TITLE} ({index}/{total})"
        embed = discord.Embed(
            title=title,
            description=chunk,
        )
        embed.add_field(name="Role", value=role.mention, inline=False)
        embed.add_field(name="Total members", value=str(len(members)), inline=True)
        embed.set_footer(text="Press the button below to add or remove the role.")
        embeds.append(embed)

    return embeds


class RoleToggleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label=BUTTON_LABEL,
        style=discord.ButtonStyle.primary,
        custom_id="persistent_role_toggle_button"
    )
    async def toggle_role(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Could not resolve your member data.", ephemeral=True)
            return

        role = guild.get_role(ROLE_ID)
        if role is None:
            await interaction.response.send_message("Configured role was not found.", ephemeral=True)
            return

        member = interaction.user

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Self-removed via leaderboard button")
                action = "removed from"
            else:
                await member.add_roles(role, reason="Self-added via leaderboard button")
                action = "added to"

            await interaction.response.send_message(
                f"You were {action} {role.mention}.",
                ephemeral=True
            )

            await refresh_leaderboard_message(guild)

        except discord.Forbidden:
            await interaction.response.send_message(
                "I do not have permission to manage that role.",
                ephemeral=True
            )
        except Exception:
            log.exception("Failed while toggling role")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Something went wrong while updating your role.",
                    ephemeral=True
                )


async def get_target_channel(guild: discord.Guild) -> discord.TextChannel:
    channel = guild.get_channel(CHANNEL_ID)
    if channel is None:
        fetched = await bot.fetch_channel(CHANNEL_ID)
        if not isinstance(fetched, discord.TextChannel):
            raise RuntimeError("Configured CHANNEL_ID is not a text channel")
        return fetched
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Configured CHANNEL_ID is not a text channel")
    return channel


async def get_or_create_leaderboard_message(guild: discord.Guild) -> discord.Message:
    global MESSAGE_ID

    channel = await get_target_channel(guild)

    if MESSAGE_ID:
        try:
            return await channel.fetch_message(MESSAGE_ID)
        except discord.NotFound:
            log.warning("Configured MESSAGE_ID not found; creating a new message")
        except Exception:
            log.exception("Failed to fetch configured message; creating a new one")

    embeds = await build_embeds(guild)
    message = await channel.send(embeds=embeds, view=RoleToggleView())
    MESSAGE_ID = message.id

    log.warning(
        "Created new leaderboard message with ID %s. Put this in Railway as MESSAGE_ID.",
        MESSAGE_ID
    )
    return message


refresh_lock = asyncio.Lock()


async def refresh_leaderboard_message(guild: discord.Guild) -> None:
    async with refresh_lock:
        message = await get_or_create_leaderboard_message(guild)
        embeds = await build_embeds(guild)
        await message.edit(embeds=embeds, view=RoleToggleView())
        log.info("Leaderboard message refreshed")


@bot.event
async def on_ready() -> None:
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)

    bot.add_view(RoleToggleView())

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        guild = await bot.fetch_guild(GUILD_ID)

    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        log.info("Synced %s app commands to guild %s", len(synced), GUILD_ID)
    except Exception:
        log.exception("Failed to sync app commands")

    try:
        full_guild = bot.get_guild(GUILD_ID)
        if full_guild is not None:
            await refresh_leaderboard_message(full_guild)
    except Exception:
        log.exception("Failed initial leaderboard refresh")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    watched_role_before = any(r.id == ROLE_ID for r in before.roles)
    watched_role_after = any(r.id == ROLE_ID for r in after.roles)

    if watched_role_before != watched_role_after:
        await refresh_leaderboard_message(after.guild)


@tree.command(
    name="leaderboard_refresh",
    description="Force refresh the leaderboard message",
    guild=discord.Object(id=GUILD_ID)
)
async def leaderboard_refresh(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This command must be used in the server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    await refresh_leaderboard_message(interaction.guild)
    await interaction.followup.send("Leaderboard refreshed.", ephemeral=True)


@tree.command(
    name="leaderboard_post",
    description="Create a new leaderboard message in the configured channel",
    guild=discord.Object(id=GUILD_ID)
)
async def leaderboard_post(interaction: discord.Interaction) -> None:
    global MESSAGE_ID

    if interaction.guild is None:
        await interaction.response.send_message("This command must be used in the server.", ephemeral=True)
        return

    channel = await get_target_channel(interaction.guild)
    embeds = await build_embeds(interaction.guild)
    message = await channel.send(embeds=embeds, view=RoleToggleView())
    MESSAGE_ID = message.id

    await interaction.response.send_message(
        f"Posted new leaderboard message. New MESSAGE_ID: `{MESSAGE_ID}`",
        ephemeral=True
    )
    log.warning("New leaderboard message posted with MESSAGE_ID=%s", MESSAGE_ID)


bot.run(TOKEN)