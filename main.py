import os
import discord
from discord.ext import commands
from discord.ui import View, Button
from flask import Flask
from threading import Thread
import logging

# ---------- Configuration (change IDs if needed) ----------
TICKET_CHANNEL_ID = 1439198296345149461   # channel where !hi posts the request embed
RULES_CHANNEL_ID = 1439259599420264459    # rules channel mention inside the embed
ROLE_IDS_CAN_CLAIM = [1439374429904965832, 1439971194228179076]  # roles allowed to claim
GUILD_ID = None  # optional: set guild id if you want to restrict some actions (not required)
# --------------------------------------------------------

# Setup logging
logging.basicConfig(level=logging.INFO)

# Keep-alive (Railway)
app = Flask("keepalive")

@app.route("/")
def home():
    return "Bot is running!"

def run_keepalive():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_keepalive, daemon=True)
    t.start()

# Intents - required for prefix message commands
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Views & Buttons ----------

class RequestTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Request Ticket", style=discord.ButtonStyle.primary, custom_id="request_ticket"))

class ClaimTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket"))

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        # Check roles
        allowed = any(role.id in ROLE_IDS_CAN_CLAIM for role in interaction.user.roles)
        if not allowed:
            await interaction.response.send_message("You can't claim this ticket.", ephemeral=True)
            return

        ticket_channel = interaction.channel
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command must be used in a guild channel.", ephemeral=True)
            return

        # Remove Claim button from message (clear view items)
        self.clear_items()
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        # Adjust channel permissions:
        # - Default: no view
        # - Ticket owner: view + send
        # - Claiming middleman (member): view + send
        # - (Optional) Other middleman roles: keep view True but send False (so they can see but not talk)
        overwrites = ticket_channel.overwrites_for(guild.default_role)
        overwrites.view_channel = False
        await ticket_channel.set_permissions(guild.default_role, overwrite=overwrites)

        # Find the ticket owner from channel name or from first message - we stored it in topic below
        ticket_owner = None
        if ticket_channel.topic:
            # our topic format: "Ticket for: <user_id>"
            if ticket_channel.topic.startswith("Ticket for:"):
                try:
                    uid = int(ticket_channel.topic.split(":")[1].strip())
                    ticket_owner = guild.get_member(uid) or await guild.fetch_member(uid)
                except Exception:
                    ticket_owner = None

        # Ensure claiming member has send permissions
        await ticket_channel.set_permissions(interaction.user, view=True, send_messages=True)

        # Ensure ticket owner can send & view
        if ticket_owner:
            await ticket_channel.set_permissions(ticket_owner, view=True, send_messages=True)

        # For all roles in ROLE_IDS_CAN_CLAIM, set view=True but send=False (so only the claiming user can send)
        for rid in ROLE_IDS_CAN_CLAIM:
            role = guild.get_role(rid)
            if role:
                await ticket_channel.set_permissions(role, view=True, send_messages=False)

        # Notify in channel
        await ticket_channel.send(f"{interaction.user.mention} will be your middleman.")

        # Ephemeral confirm to the claimer
        await interaction.response.send_message("You claimed this ticket.", ephemeral=True)

# ---------- Bot Events & Commands ----------

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logging.info("Ready.")

@bot.command()
@commands.guild_only()
async def hi(ctx: commands.Context):
    """
    Sends the ticket request embed in the configured TICKET_CHANNEL_ID.
    Use: !hi
    """
    guild = ctx.guild
    # try to fetch the configured channel
    dest = guild.get_channel(TICKET_CHANNEL_ID)
    if dest is None:
        # maybe the channel is in another guild; attempt global fetch
        try:
            dest = await bot.fetch_channel(TICKET_CHANNEL_ID)
        except Exception:
            await ctx.send("Configured ticket channel not found. Check TICKET_CHANNEL_ID.")
            return

    embed = discord.Embed(
        title="Ticket system",
        description=f"**Click here to request a middleman**\n**For information about Middleman rules, Please check here <#{RULES_CHANNEL_ID}>**",
        color=discord.Color.white()
    )

    view = RequestTicketView()
    try:
        await dest.send(embed=embed, view=view)
        await ctx.send(f"Ticket message posted in {dest.mention}", delete_after=8)
    except discord.Forbidden:
        await ctx.send("I don't have permission to send messages in the ticket channel.")
    except Exception as e:
        await ctx.send(f"Failed to send ticket embed: {e}")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # handle the "request_ticket" button
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id")
    if custom_id == "request_ticket":
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This must be used in a guild.", ephemeral=True)
            return

        user = interaction.user

        # Create ticket channel name and overwrites
        safe_name = f"ticket-{user.name}".replace(" ", "-")[:90]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        # Give middleman roles view permission initially (they should be able to see the ticket so they can claim)
        for rid in ROLE_IDS_CAN_CLAIM:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)

        # Create the channel under the same category as the interaction channel if possible
        category = interaction.channel.category if interaction.channel else None
        try:
            ticket_channel = await guild.create_text_channel(
                name=safe_name,
                overwrites=overwrites,
                category=category,
                topic=f"Ticket for: {user.id}"
            )
        except discord.Forbidden:
            await interaction.response.send_message("Bot missing permissions to create channels.", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"Failed to create ticket channel: {e}", ephemeral=True)
            return

        # Send the ticket embed and the Claim button inside the ticket channel
        embed = discord.Embed(
            title="Ticket system",
            description="Please wait for a Middleman to claim the ticket",
            color=discord.Color.white()
        )
        view = ClaimTicketView()
        try:
            await ticket_channel.send(f"{user.mention}", embed=embed, view=view)
        except Exception:
            # fallback - send without view if that fails
            await ticket_channel.send(f"{user.mention}\nPlease wait for a Middleman to claim the ticket")

        # Respond to the interaction with ephemeral message linking the ticket
        await interaction.response.send_message(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)

# ---------- Run ----------
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logging.critical("DISCORD_TOKEN not found in environment variables. Exiting.")
        raise SystemExit("DISCORD_TOKEN env var is required.")
    bot.run(token)
