import os
from dotenv import load_dotenv
import discord
from openai import OpenAI
import asyncio
from collections import deque
from algorithm_memory import load_memory, background_memory_update, format_memory_naturally

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
	raise SystemExit("DISCORD_TOKEN not set")

GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

ai = OpenAI(api_key=os.getenv("OPENAI_KEY"))
SHORT_TERM = int(os.getenv("SHORT_TERM_WINDOW", 50))
short_term_memory = deque(maxlen=SHORT_TERM)
message_counter = 0
UPDATE_FREQUENCY = int(os.getenv("UPDATE_FREQUENCY", 20))

SYSTEM_PROMPT = ""
with open(os.getenv("PROMPT_FILE")) as f:
	SYSTEM_PROMPT = f.read()

@client.event
async def on_ready():
	print(f"Logged in as {client.user} (ID: {client.user.id})")
	try:
		if GUILD_ID:
			await tree.sync(guild=discord.Object(id=GUILD_ID))
			print(f"Synced app commands to guild {GUILD_ID}")
		else:
			await tree.sync()
			print("Synced global app commands")
	except Exception as e:
		print("Sync failed:", e)

@client.event
async def on_message(message: discord.Message):
	global message_counter
	if message.author.bot or message.author == client.user or message.channel.id not in [1428968893111865384]:
		return

	try:
		short_term_memory.append(message)
		memory = format_memory_naturally(load_memory())
		print(f"\n{message.author.name}: {message.content}")

		async with message.channel.typing():
			resp = await asyncio.to_thread(
				ai.chat.completions.create,
				model=os.getenv("MODEL"),
				messages=[
					{"role": "system", "content": SYSTEM_PROMPT.format(memory = memory)},
					*[{
						"role": "user" if msg.author != client.user else "assistant", 
						"content": msg.content if msg.author == client.user else f"{msg.author.name}: {msg.content}"
					} for msg in list(short_term_memory)]
				],
				temperature=0.9
			)
			content = resp.choices[0].message.content
		
		# Send message and capture it for memory
		print("AI: " + content)
		sent_message = await message.channel.send(content)
		short_term_memory.append(sent_message)
		
		message_counter += 1
		# schedule memory update
		if message_counter >= UPDATE_FREQUENCY:
			message_counter = 0
			task = asyncio.create_task(background_memory_update(list(short_term_memory)[-SHORT_TERM:], client.user.id))

			def _mem_done(t):
				print()
				try:
					exc = t.exception()
				except asyncio.CancelledError:
					print("Memory update was cancelled")
					return
				except Exception as e:
					print("Memory update callback error:", repr(e))
					return
				if exc:
					print(f"Memory update error: {repr(exc)}")
				else:
					print("Updated memory")

			task.add_done_callback(_mem_done)
		
	except Exception as e:
		print("OpenAI request failed:", e)

@tree.command(name="ping", description="Pong")
async def ping(interaction: discord.Interaction):
	latency_ms = round(client.latency * 1000)
	await interaction.response.send_message(f"Pong! {latency_ms}ms")

if __name__ == "__main__":
	client.run(DISCORD_TOKEN)