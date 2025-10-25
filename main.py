import os, sys, discord, asyncio, uptime, setenv
from dotenv import load_dotenv
from openai import AsyncOpenAI
from collections import deque
from algorithm_memory import load_memory, background_memory_update, format_memory_naturally
from discord.ext import commands

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
	raise SystemExit("DISCORD_TOKEN not set")

GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

ai = AsyncOpenAI(api_key=os.getenv("API_KEY"), base_url="https://api.llm7.io/v1")
serkan = AsyncOpenAI(api_key=os.getenv("OPENAI_KEY"))
SHORT_TERM = int(os.getenv("SHORT_TERM_WINDOW", 50))
short_term_memory: deque[discord.Message] = deque(maxlen=SHORT_TERM)
message_counter = 0
UPDATE_FREQUENCY = int(os.getenv("UPDATE_FREQUENCY", 20))

SYSTEM_PROMPT = ""
with open(os.getenv("PROMPT_FILE")) as f:
	SYSTEM_PROMPT = f.read()

async def get_messages(memory):
	messages = [{"role": "system", "content": SYSTEM_PROMPT.format(memory=memory)}]
	steal_key = False

	for msg in list(short_term_memory):
		text_template = ""
		role = ""
		if msg.author == bot.user:
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
					steal_key = True
					content.append({"type": "image_url", "image_url": {"url": att.url}})
		
		messages.append({
			"role": role,
			"content": content
		})
		print(content)
	
	return {"messages": messages, "serkan": steal_key}

async def describe_image(message: discord.Message):
	images = []
	for att in message.attachments:
		if att.content_type.startswith("image/"):
			images.append(att)
	
	if images:
		resp = await serkan.chat.completions.create(
			model="gpt-5-nano",
			messages=[
				{"role": "system", "content": "You are a vision AI. Summarise any attached images in as much detail as possible."},
				{"role": "user", "content": [
					{"type": "text", "text": "Describe these images in detail."},
					*[{"type": "image_url", "image_url": {"url": att.url}} for att in images]
				]}
			]
		)
		return resp
	return ""

@bot.event
async def on_ready():
	print(f"Logged in as {bot.user} (ID: {bot.user.id})")
	try:
		if GUILD_ID:
			await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
			print(f"Synced app commands to guild {GUILD_ID}")
		else:
			await bot.tree.sync()
			print("Synced global app commands")
	except Exception as e:
		print("Sync failed:", e)

@bot.event
async def on_message(message: discord.Message):
	global message_counter
	if message.author.bot or message.author == bot.user or message.channel.id not in [1428968893111865384]:
		return

	try:
		short_term_memory.append(message)
		memory = format_memory_naturally(load_memory())
		print(f"\n{message.author.name}: {message.content}")
		data = await get_messages(memory)

		async with message.channel.typing():
			if data["serkan"]:
				resp, desc = await asyncio.gather(
					serkan.chat.completions.create(model="gpt-5-nano", messages=data["messages"]),
					describe_image(message)
				)
				short_term_memory[-1].attachments = []
				short_term_memory[-1].content += f"\nAttached images:\n{desc.choices[0].message.content}"
			else:
				resp = await ai.chat.completions.create(
					model="gpt-5-chat",
					messages=data["messages"],
					temperature=1.2
				)
		content = resp.choices[0].message.content
		print("AI: " + content)
		sent_message = await message.channel.send(content)
		short_term_memory.append(sent_message)
		
		message_counter += 1
		# schedule memory update
		if message_counter >= UPDATE_FREQUENCY:
			message_counter = 0
			task = asyncio.create_task(background_memory_update(list(short_term_memory)[-SHORT_TERM:], bot.user.id))

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

@bot.tree.command(name="ping", description="Get latency.")
async def ping(interaction: discord.Interaction):
	latency_ms = round(bot.latency * 1000)
	await interaction.response.send_message(f"Pong! {latency_ms}ms")

@bot.tree.command(name="uptime", description="Get uptime.")
async def get_uptime(interaction: discord.Interaction):
	await interaction.response.send_message(f"Server started <t:{int(uptime.boottime().timestamp())}:R>.")

@bot.tree.command(name="kill", description="Goodnight!")
async def refresh(interaction: discord.Interaction):
	if interaction.user.id != 1337909802931716197:
		await interaction.response.send_message("You're not authorised LMAO")
	else:
		await interaction.response.send_message("Restarting all services. Goodnight.")
		sys.exit(0)

@bot.tree.command(name="secret", description="Set a secret.")
async def set_secret(interaction: discord.Interaction, key: str, value: str):
	if interaction.user.id != 1337909802931716197:
		await interaction.response.send_message("You're not authorised LMAO")
	else:
		setenv.set_value(key, value)
		await interaction.response.send_message("Added secret to .env", ephemeral=True)

if __name__ == "__main__":
	bot.run(DISCORD_TOKEN)