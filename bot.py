# Twitch Live Notification Bot 
# Monitors a Twitch channel and sends a Discord alert when the streamer goes live. 
# When stream ends, the alert is edited to show "was live" and adds a VOD link.
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
streamer_avatar_url = None 
# ------------------------------------------------------------------------------
# Fetches the streamer's Twitch profile picture and sets it as the bot's Discord avatar.
# Only runs on startup. Note: Discord rate limits avatar changes to ~2 per hour. 
async def set_bot_avatar(session, token, username):
    global streamer_avatar_url
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
        streamer_avatar_url = avatar_url # Save it globally.
    # Download image and set it as bot's avatar
    async with session.get(avatar_url) as r:
        avatar_bytes = await r.read()
        await client.user.edit(avatar=avatar_bytes)
        print(f"Bot avatar set to {username}'s profile picture.")
# Get Twitch Token.
# Authenticates with Twitch using client credentials and returns a bearer token. 
# This token is required for all Twitch API requests.
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
    
# Checks if the given Twitch username is currently live. 
# Returns the stream object if live, or None if offline. 
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
# Function for getting Twitch VOD to use when stream has concluded.
# First resolves the username to a user ID, then queries the videos endpoint. 
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

# Main loop - checks Twitch every POLL_INTERVAL seconds. 
# Sends a live alert when the streamer goes live, and edits it when they go offline. 
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
            try:
                stream = await get_stream(session, twitch_token, TWITCH_USERNAME)
                is_live = stream is not None

                if is_live and not was_live:
                    # Streamer is live! Sending alert now... 
                    last_vod_id = stream["id"]
                    embed = discord.Embed(
                        title=f" {stream['user_name']} is now live!",
                        description=stream.get("title", ""),
                        url=f"https://twitch.tv/{TWITCH_USERNAME}",
                        color=0x9146FF
                    )
                    embed.add_field(name="Game", value=stream.get("game_name", "Unknown"))
                    embed.add_field(name="Viewers", value=stream.get("viewer_count", 0))
                    embed.set_thumbnail(url=streamer_avatar_url)  # small profile pic top right
                    embed.set_image(url=stream['thumbnail_url'].replace("{width}x{height}", "1280x720"))  # big stream preview
                    live_message = await channel.send(content="@everyone", embed=embed)
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
            
            except Exception as e:
                print(f"Error during poll: {e}, retrying in {POLL_INTERVAL}s...")

            await asyncio.sleep(POLL_INTERVAL)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{TWITCH_USERNAME} on Twitch"
        )
    target_user = await self.fetch_user(485957450009149451)
    await target_user.send("https://www.twitch.tv/poofed__")
    ) 
    client.loop.create_task(poll_twitch())


client.run(DISCORD_TOKEN)