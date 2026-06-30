import asyncio
import traceback
import discord
from discord import app_commands
from discord.ext import commands
import wavelink

LAVALINK_NODES = [
    {"host": "lavalinkv4.serenetia.com", "port": 443, "password": "https://seretia.link/discord", "secure": True, "identifier": "Serenetia-HTTPS"},
    {"host": "lavalinkv4.serenetia.com", "port": 80, "password": "https://seretia.link/discord", "secure": False, "identifier": "Serenetia-HTTP"},
    {"host": "lavalink.jirayu.net", "port": 443, "password": "youshallnotpass", "secure": True, "identifier": "Jirayu-HTTPS"},
    {"host": "lavalink.jirayu.net", "port": 13592, "password": "youshallnotpass", "secure": False, "identifier": "Jirayu-HTTP"},
    {"host": "lava-v4.millohost.my.id", "port": 443, "password": "https://discord.gg/mjS5J2K3ep", "secure": True, "identifier": "MilloHost"},
    {"host": "sg1-nodelink.nyxbot.app", "port": 3000, "password": "nyxbot.app/support", "secure": False, "identifier": "NyxBot-SG1"},
    {"host": "sg2-nodelink.nyxbot.app", "port": 3000, "password": "nyxbot.app/support", "secure": False, "identifier": "NyxBot-SG2"},
]

async def connect_lavalink(bot: commands.Bot) -> None:
    if wavelink.Pool.nodes:
        return

    nodes_to_connect = []
    for node_data in LAVALINK_NODES:
        protocol = "https" if node_data["secure"] else "http"
        uri = f"{protocol}://{node_data['host']}:{node_data['port']}"
        
        node = wavelink.Node(
            uri=uri,
            password=node_data["password"],
            identifier=node_data["identifier"]
        )
        nodes_to_connect.append(node)

    try:
        await wavelink.Pool.connect(client=bot, nodes=nodes_to_connect)
        print(f"Successfully connected {len(nodes_to_connect)} nodes to the global Wavelink Pool!")
    except Exception as e:
        print(f"Failed to connect to Lavalink: {e}")


class MusicPlayer(wavelink.Player):
    """
    Custom player class. Since Wavelink natively manages your connection handshakes,
    we leave internal voice protocol methods completely untouched to prevent multi-node crashes.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await connect_lavalink(self.bot)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"Lavalink node '{payload.node.identifier}' is ready! Session ID: {payload.session_id}")

    @app_commands.command(
        name="play", description="Play music from YouTube or other sources"
    )
    @app_commands.describe(query="YouTube URL or search query")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message(
                "You need to be in a voice channel!", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            channel = interaction.user.voice.channel
            vc: MusicPlayer = interaction.guild.voice_client

            if not vc:
                vc = await channel.connect(cls=MusicPlayer)
                print(f"Connected to voice channel: {channel.name}")

            print(f"Searching for: {query}")

            if query.startswith("http://") or query.startswith("https://"):
                tracks = await wavelink.Playable.search(query)
            else:
                tracks = await wavelink.Playable.search(f"ytsearch:{query}")

            if not tracks:
                await interaction.followup.send("No tracks found!")
                return

            track = tracks[0]

            print(f"Track found: {track.title}")
            print(f"Author: {track.author}")
            print(f"Duration: {track.length}ms")
            print(f"URI: {track.uri}")
            print(f"Source: {track.source}")

            await vc.play(track)

            embed = discord.Embed(
                title="Now Playing",
                description=f"**{track.title}**",
                color=discord.Color.green(),
            )

            embed.add_field(name="Author", value=track.author, inline=True)
            embed.add_field(
                name="Duration",
                value=f"{track.length // 60000}:{(track.length // 1000) % 60:02d}",
                inline=True,
            )
            embed.add_field(
                name="Source", value=str(track.source).upper(), inline=True
            )

            if track.artwork:
                embed.set_thumbnail(url=track.artwork)

            await interaction.followup.send(embed=embed)

            print(f"Started playing: {track.title}")
            print(f"Player state: playing={vc.playing}, paused={vc.paused}")

        except wavelink.exceptions.LavalinkException as e:
            print(f"Lavalink error: {e}")
            await interaction.followup.send(f"Lavalink error: {e}")

        except Exception as e:
            print(f"Error playing track: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"Error: {e}")

    @app_commands.command(
        name="stop", description="Stop playing and disconnect"
    )
    async def stop(self, interaction: discord.Interaction):
        vc: MusicPlayer = interaction.guild.voice_client

        if not vc:
            await interaction.response.send_message(
                "Not connected to a voice channel!", ephemeral=True
            )
            return

        await vc.disconnect()
        await interaction.response.send_message("Stopped and disconnected!")
        print("Stopped playback and disconnected")

    @app_commands.command(name="pause", description="Pause the current track")
    async def pause(self, interaction: discord.Interaction):
        vc: MusicPlayer = interaction.guild.voice_client

        if not vc or not vc.playing:
            await interaction.response.send_message(
                "Nothing is playing!", ephemeral=True
            )
            return

        await vc.pause(True)
        await interaction.response.send_message("Paused!")
        print("Paused playback")

    @app_commands.command(
        name="resume", description="Resume the current track"
    )
    async def resume(self, interaction: discord.Interaction):
        vc: MusicPlayer = interaction.guild.voice_client

        if not vc or not vc.paused:
            await interaction.response.send_message(
                "Nothing is paused!", ephemeral=True
            )
            return

        await vc.pause(False)
        await interaction.response.send_message("Resumed!")
        print("Resumed playback")

    @app_commands.command(
        name="status", description="Check active Lavalink nodes and status"
    )
    async def status(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Bot & Lavalink Cluster Status", color=discord.Color.blue())
        nodes = wavelink.Pool.nodes

        if nodes:
            node_status_list = []
            for name, node in nodes.items():
                status_icon = "🟢" if node.status == wavelink.NodeStatus.CONNECTED else "🔴"
                node_status_list.append(f"{status_icon} **{name}**: Players: {len(node.players)}")
            
            embed.add_field(
                name="Connected Nodes",
                value="\n".join(node_status_list),
                inline=False,
            )
        else:
            embed.add_field(
                name="Connected Nodes", value="❌ No active nodes in pool", inline=False
            )

        vc: MusicPlayer = interaction.guild.voice_client

        if vc:
            status_text = (
                f"Channel: {vc.channel.name}\n"
                f"Assigned Node: **{vc.node.identifier}**\n"
                f"Playing: {vc.playing}\n"
                f"Paused: {vc.paused}\n"
            )

            if vc.current:
                status_text += f"\n**Track:** {vc.current.title}"

            embed.add_field(
                name="Current Guild Voice Status", value=status_text, inline=False
            )
        else:
            embed.add_field(
                name="Current Guild Voice Status",
                value="Not connected to voice in this guild",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ):
        print(f"Track started: {payload.track.title}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ):
        print(f"Track ended: {payload.track.title} | Reason: {payload.reason}")

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ):
        print(f"Track exception: {payload.track.title} | Error: {payload.exception}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
