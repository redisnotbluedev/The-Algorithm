import os, sys, discord, asyncio, uptime, base64
from dotenv import load_dotenv
from openai import OpenAI
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

ai = OpenAI(api_key=os.getenv("API_KEY"), base_url="https://api.llm7.io/v1")
SHORT_TERM = int(os.getenv("SHORT_TERM_WINDOW", 50))
short_term_memory: deque[discord.Message] = deque(maxlen=SHORT_TERM)
message_counter = 0
UPDATE_FREQUENCY = int(os.getenv("UPDATE_FREQUENCY", 20))

SYSTEM_PROMPT = ""
with open(os.getenv("PROMPT_FILE")) as f:
	SYSTEM_PROMPT = f.read()

async def get_messages(memory):
	messages = [{"role": "system", "content": SYSTEM_PROMPT.format(memory=memory)}]

	for msg in list(short_term_memory):
		text_template = ""
		role = ""
		if msg.author == client.user:
			role = "assistant"
			text_template = "{msg.content}"
		else:
			role = "user"
			text_template = "{msg.author.name}: {msg.content}"
		
		if text_template:
			content = [{"type": "text", "text": text_template.format(msg=msg)}]
		if msg.attachments:
			for att in msg.attachments:
				mime = att.content_type
				if mime.startswith("image/"):
					content.append({"type": "image_url", "image_url": {"url": base64.b64encode(await att.read()).decode('utf-8')}})
		
		messages.append({
			"role": role,
			"content": content
		})
		print(content)
	
	return messages

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
		messages = await get_messages(memory)

		async with message.channel.typing():
			resp = await asyncio.to_thread(
				ai.chat.completions.create,
				model="gpt-5-chat",
				messages=messages,
				temperature=0.9
			)
			content = resp.choices[0].message.content
		
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

@tree.command(name="ping", description="Get latency.")
async def ping(interaction: discord.Interaction):
	latency_ms = round(client.latency * 1000)
	await interaction.response.send_message(f"Pong! {latency_ms}ms")

@tree.command(name="uptime", description="Get uptime.")
async def uptime(interaction: discord.Interaction):
	await interaction.response.send_message(f"Server started <t:{int(uptime.boottime())}:R>.")

@tree.command(name="kill", description="Goodnight!")
async def refresh(interaction: discord.Interaction):
	if interaction.user.id != 1337909802931716197:
		await interaction.response.send_message("You're not authorised LMAO")
	else:
		await interaction.response.send_message("Restarting all services. Goodnight.")
		sys.exit(0)

if __name__ == "__main__":
	client.run(DISCORD_TOKEN)