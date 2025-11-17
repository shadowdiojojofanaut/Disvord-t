import os
import discord
from discord.ext import commands
from discord.ui import View, Button
from flask import Flask
from threading import Thread
import logging

# ---------- Configuration ----------
TICKET_CHANNEL_ID = 1439198296345149461   # channel where !hi posts ticket embed
RULES_CHANNEL_ID = 1439259599420264459    # rules channel
ROLE_IDS_CAN_CLAIM = [1439374429904965832, 1439971194228179076]  # allowed roles
# -----------------------------------

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)

# ---------- Keepalive (Railway) ----------
app = Flask("keepalive")

@app.route("/")
def home():
    return "Bot is running!"

def run_keepalive():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_keepalive, daemon=True)
    t.start()

# ---------- Bot ----------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Ticket Request Button ----------
class RequestTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Request Ticket", style=discord.ButtonStyle.primary, custom_id="request_ticket"))

# ---------- Claim Button ----------
class ClaimTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket"))

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        allowed = any(role.id in ROLE_IDS_CAN_CLAIM for role in interaction.user.roles)
        if not allowed:
            await interaction.response.send_message("You can't claim this ticket.", ephemeral=True)
            return

        ticket_channel = interaction.channel
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        # Remove Claim button
        self.clear_items()
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        # Get ticket owner from topic
        ticket_owner = None
        if ticket_channel.topic and ticket_channel.topic.startswith("Ticket for:"):
            try:
                uid = int(ticket_channel.topic.split(":")[1].strip())
                ticket_owner = guild.get_member(uid) or await guild.fetch_member(uid)
            except:
                ticket_owner = None

        # Set permissions
        overwrites = ticket_channel.overwrites
        # default role: can't view
        await ticket_channel.set_permissions(guild.default_role, view_channel=False)
        # ticket owner: view + send
        if ticket_owner:
            await ticket_channel.set_permissions(ticket_owner, view=True, send_messages=True)
        # claiming middleman: view + send
        await ticket_channel.set_permissions(interaction.user, view=True, send_messages=True)
        # other middleman roles: view True, send False
        for rid in ROLE_IDS_CAN_CLAIM:
            role = guild.get_role(rid)
            if role:
                await ticket_channel.set_permissions(role, view=True, send_messages=False)

        # Notify ticket
        await ticket_channel.send(f"{interaction.user.mention} will be your middleman.")

        # Ephemeral confirmation
        await interaction.response.send_message("You claimed this ticket.", ephemeral=True)

# ---------- Bot Events & Commands ----------
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logging.info("Ready.")

@bot.command()
@commands.guild_only()
async def hi(ctx: commands.Context):
    guild = ctx.guild
    dest = guild.get_channel(TICKET_CHANNEL_ID)
    if dest is None:
        try:
            dest = await bot.fetch_channel(TICKET_CHANNEL_ID)
        except Exception:
            await ctx.send("Configured ticket channel not found. Check TICKET_CHANNEL_ID.")
            return

    embed = discord.Embed(
        title="Ticket system",
        description=f"**Click here to request a middleman**\n**For information about Middleman rules, Please check here <#{RULES_CHANNEL_ID}>**",
        color=discord.Color.blurple()  # FIXED color
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
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id")
    if custom_id == "request_ticket":
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)
            return

        user = interaction.user
        safe_name = f"ticket-{user.name}".replace(" ", "-")[:90]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        for rid in ROLE_IDS_CAN_CLAIM:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)

        category = interaction.channel.category if interaction.channel else None
        try:
            ticket_channel = await guild.create_text_channel(
                name=safe_name,
                overwrites=overwrites,
                category=category,
                topic=f"Ticket for: {user.id}"
            )
        except Exception as e:
            await interaction.response.send_message(f"Failed to create ticket: {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title="Ticket system",
            description="Please wait for a Middleman to claim the ticket",
            color=discord.Color.blurple()
        )
        view = ClaimTicketView()
        try:
            await ticket_channel.send(f"{user.mention}", embed=embed, view=view)
        except:
            await ticket_channel.send(f"{user.mention}\nPlease wait for a Middleman to claim the ticket")

        await interaction.response.send_message(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)

# ---------- Run ----------
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logging.critical("DISCORD_TOKEN not found in environment variables. Exiting.")
        raise SystemExit("DISCORD_TOKEN env var is required.")
    bot.run(token)
