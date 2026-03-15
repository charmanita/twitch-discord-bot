import discord 
import aiohttp
import asyncio
import os 
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "bot.env"))
# Config for the bot to be able to work properly. 
# -----------------------------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_USERNAME = os.getenv("TWITCH_USERNAME")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 60))

# End of config 
# ------------------------------------------------------------------------------
intents = discord.Intents.default()
client = discord.Client(intents=intents)

twitch_token = None 
was_live = False     # Tracks to previous state to avoid dupe alerts.
live_message = None # Stores sent Discord message to edit later. 
last_vod_id = None # Stores stream ID for VOD lookup post-stream. 
# ------------------------------------------------------------------------------
# Set Bot Avatar to Twitch Streamer Avatar
async def set_bot_avatar(session, token, username):
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }
    # Get profile picture URL
    async with session.get(
        "https://api.twitch.tv/helix/users",
        headers=headers,
        params={"login": username}
    ) as r:
        data = await r.json()
        users = data.get("data", [])
        if not users:
            return
        avatar_url = users[0]["profile_image_url"]
    # Download image and set it as bot's avatar
    async with session.get(avatar_url) as r:
        avatar_bytes = await r.read()
        await client.user.edit(avatar=avatar_bytes)
        print(f"Bot avatar set to {username}'s profile picture.")
# Get Twitch Token.
async def get_twitch_token(session):
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    async with session.post(url, params=params) as r:
        data = await r.json()
        return data ["access_token"]
    
# Function for getting stream
async def get_stream(session, token, username):
    url = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }
    params = {"user_login": username}
    async with session.get(url, headers=headers, params=params) as r:
        data = await r.json()
        streams = data.get("data", [])
        return streams[0] if streams else None

async def get_vod(session, token, username):
    url = "https://api.twitch.tv/helix/videos"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }
    # Get user ID from username 
    async with session.get(
        "https://api.twitch.tv/helix/users",
        headers=headers,
        params={"login": username}
    ) as r: 
        data = await r.json()
        users = data.get("data", [])
        if not users:
            return None
        user_id = users[0]["id"]
    # Get most recent VOD. 
    async with session.get(
        url, 
        headers=headers,
        params={"user_id": user_id, "first": 1, "type": "archive"}
    ) as r:
        data = await r.json()
        videos = data.get("data", [])
        return videos[0]["url"] if videos else None

async def poll_twitch():
    global twitch_token, was_live, live_message, last_vod_id
    await client.wait_until_ready()
    channel = client.get_channel(DISCORD_CHANNEL_ID)

    async with aiohttp.ClientSession() as session:
        twitch_token = await get_twitch_token(session)
        try: 
            await set_bot_avatar(session, twitch_token, TWITCH_USERNAME)
        except discord.HTTPException as e:
            print(f"Could not set avatar: {e}")
        while not client.is_closed():
            stream = await get_stream(session, twitch_token, TWITCH_USERNAME)
            is_live = stream is not None

            if is_live and not was_live:
                # Poofed is live! Sending alert now... 
                last_vod_id = stream["id"]
                embed = discord.Embed(
                    title=f" {stream['user_name']} is now live!",
                    description=stream.get("title", ""),
                    url=f"https://twitch.tv/{TWITCH_USERNAME}",
                    color=0x9146FF
                )
                embed.add_field(name="Game", value=stream.get("game_name", "Unknown"))
                embed.add_field(name="Viewers", value=stream.get("viewer_count", 0))
                embed.set_thumbnail(url=stream['thumbnail_url'].replace("{width}x{height}", "1280x720"))
                live_message = await channel.send(embed=embed)
            elif not is_live and was_live and live_message:
                vod_url = await get_vod(session, twitch_token, TWITCH_USERNAME)
                embed = discord.Embed(
                    title=f"{TWITCH_USERNAME} was live",
                    color=0x6441A5,
                )
                if vod_url: 
                    embed.add_field(name="Watch VOD", value=vod_url)
                else:
                    embed.add_field(name="VOD", value="Not available.")
                await live_message.edit(embed=embed)
                live_message = None

            was_live = is_live
            await asyncio.sleep(POLL_INTERVAL)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{TWITCH_USERNAME} on Twitch"
        )
    ) 
    client.loop.create_task(poll_twitch())


client.run(DISCORD_TOKEN)