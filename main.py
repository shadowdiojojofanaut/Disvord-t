import os
import discord
from discord.ext import commands
from discord.ui import Button, View

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Replace with your IDs
TICKET_CHANNEL_ID = 1439198296345149461
RULES_CHANNEL_ID = 1439259599420264459
ROLE_IDS_CAN_CLAIM = [1439374429904965832, 1439971194228179076]

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Request Ticket", style=discord.ButtonStyle.primary, custom_id="request_ticket"))

class ClaimButtonView(View):
    def __init__(self, middleman_role_ids):
        super().__init__(timeout=None)
        self.middleman_role_ids = middleman_role_ids

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: Button):
        if not any(role.id in self.middleman_role_ids for role in interaction.user.roles):
            await interaction.response.send_message("You can't claim this ticket.", ephemeral=True)
            return

        # Remove button after claimed
        self.clear_items()
        await interaction.message.edit(view=self)

        channel = interaction.channel
        overwrites = channel.overwrites
        for role_id in self.middleman_role_ids:
            role = channel.guild.get_role(role_id)
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        await channel.edit(overwrites=overwrites)
        await channel.send(f"{interaction.user.mention} will be your middleman.")

@bot.command()
async def hi(ctx):
    if ctx.channel.id != TICKET_CHANNEL_ID:
        return

    embed = discord.Embed(
        title="Ticket system",
        description=f"**Click here to request a middleman**\n**For information about Middleman rules, Please check here <#{RULES_CHANNEL_ID}>**",
        color=discord.Color.white()
    )
    view = TicketView()
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        if interaction.data["custom_id"] == "request_ticket":
            guild = interaction.guild
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            for role_id in ROLE_IDS_CAN_CLAIM:
                role = guild.get_role(role_id)
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                overwrites=overwrites
            )

            embed = discord.Embed(
                title="Ticket system",
                description="Please wait for a Middleman to claim the ticket",
                color=discord.Color.white()
            )
            await ticket_channel.send(embed=embed, view=ClaimButtonView(ROLE_IDS_CAN_CLAIM))

            await interaction.response.send_message(
                f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True
            )

bot.run(os.getenv("DISCORD_TOKEN"))
