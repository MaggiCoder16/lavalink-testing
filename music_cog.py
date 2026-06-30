import asyncio
import traceback
import discord
from discord import app_commands
from discord.ext import commands
import wavelink

async def connect_lavalink(bot: commands.Bot) -> None:
    if wavelink.Pool.nodes:
        return

    node = wavelink.Node(
        uri="https://lavalinkv4.serenetia.com:443",
        password="https://seretia.link/discord",
    )

    try:
        await wavelink.Pool.connect(client=bot, nodes=[node])
        print("Successfully connected to Lavalink server!")
    except Exception as e:
        print(f"Failed to connect to Lavalink: {e}")

class MusicPlayer(wavelink.Player):
    async def on_voice_state_update(self, data, /) -> None:
        channel_id = data["channel_id"]

        if not channel_id:
            if self._connected:
                await self._destroy()
            return

        self._connected = True
        self._voice_state["voice"]["session_id"] = data["session_id"]
        self._voice_state["channel_id"] = str(channel_id)

        resolved = None
        if self.guild is not None:
            resolved = self.guild.get_channel(int(channel_id))
        if resolved is None:
            resolved = self.client.get_channel(int(channel_id))  # type: ignore[arg-type]
        if resolved is not None:
            self.channel = resolved

    async def _dispatch_voice_update(self) -> None:
        assert self.guild is not None

        voice = self._voice_state["voice"]
        session_id = voice.get("session_id")
        token = voice.get("token")
        endpoint = voice.get("endpoint")
        channel_id = self._voice_state.get("channel_id")

        if not session_id or not token or not endpoint or not channel_id:
            return

        request = {
            "voice": {
                "sessionId": session_id,
                "token": token,
                "endpoint": endpoint,
                "channelId": channel_id,
            }
        }

        try:
            await self.node._update_player(self.guild.id, data=request)
        except wavelink.LavalinkException:
            await self.disconnect()
        else:
            self._connection_event.set()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await connect_lavalink(self.bot)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"Lavalink node {payload.node.identifier} is ready!")
        print(f"Session ID: {payload.session_id}")

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

            if not interaction.guild.voice_client:
                vc: MusicPlayer = await channel.connect(cls=MusicPlayer)
                print(f"Connected to voice channel: {channel.name}")
            else:
                vc: wavelink.Player = interaction.guild.voice_client

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
                name="Source", value=track.source.upper(), inline=True
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
        vc: wavelink.Player = interaction.guild.voice_client

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
        vc: wavelink.Player = interaction.guild.voice_client

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
        vc: wavelink.Player = interaction.guild.voice_client

        if not vc or not vc.paused:
            await interaction.response.send_message(
                "Nothing is paused!", ephemeral=True
            )
            return

        await vc.pause(False)
        await interaction.response.send_message("Resumed!")
        print("Resumed playback")

    @app_commands.command(
        name="status", description="Check Lavalink and bot status"
    )
    async def status(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Bot Status", color=discord.Color.blue())
        nodes = wavelink.Pool.nodes

        if nodes and len(nodes) > 0:
            node = list(nodes.values())[0]
            embed.add_field(
                name="Lavalink Node",
                value=f"Connected\nPlayers: {len(node.players)}",
                inline=True,
            )
        else:
            embed.add_field(
                name="Lavalink Node", value="Not connected", inline=True
            )

        vc: wavelink.Player = interaction.guild.voice_client

        if vc:
            status_text = (
                f"Channel: {vc.channel.name}\n"
                f"Playing: {vc.playing}\n"
                f"Paused: {vc.paused}\n"
            )

            if vc.current:
                status_text += f"\n**Current Track:**\n{vc.current.title}"

            embed.add_field(
                name="Voice Status", value=status_text, inline=False
            )
        else:
            embed.add_field(
                name="Voice Status",
                value="Not connected to voice",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ):
        """Event fired when a track starts playing"""
        print(f"Track started: {payload.track.title}")
        print(f"Player: {payload.player}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ):
        print(f"Track ended: {payload.track.title}")
        print(f"Reason: {payload.reason}")

        if payload.reason == "loadFailed":
            print("LOAD FAILED - The track failed to load/play!")
            print("This usually means:")
            print("  - Video is geo-blocked or region-restricted")
            print("  - Video is age-restricted")
            print("  - Video was deleted or made private")
            print("  - YouTube client compatibility issue")

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ):
        print(f"Track exception: {payload.track.title}")
        print(f"Error: {payload.exception}")
        print(f"Details: {payload}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
