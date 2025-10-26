import os, sys, discord, asyncio, uptime, setenv, re, time, inspect
from dotenv import load_dotenv
from openai import AsyncOpenAI
from collections import deque
from algorithm_memory import load_memory, background_memory_update, format_memory_naturally
import algorithm_tool as tools
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
short_term_memory: deque[dict] = deque(maxlen=SHORT_TERM)
message_counter = 0
UPDATE_FREQUENCY = int(os.getenv("UPDATE_FREQUENCY", 20))

SYSTEM_PROMPT = ""
with open(os.getenv("PROMPT_FILE")) as f:
	SYSTEM_PROMPT = f.read()

tool = re.compile(r"\ncall (\w+)(?: (.+))?$")
functions = tools.tools

async def get_messages(memory):
	messages = [{"role": "system", "content": SYSTEM_PROMPT.format(memory=memory, tools=tools.format_tools(functions))}]
	steal_key = False

	for msg in list(short_term_memory):
		text_template = ""
		role = ""
		if msg["a_id"] == bot.user.id:
			role = "assistant"
			text_template = "{msg[content]}"
		else:
			role = "user"
			text_template = "{msg[name]}: {msg[content]}"
		
		if text_template:
			content = [{"type": "text", "text": text_template.format(msg=msg)}]
		if msg['attachments']:
			for att in msg['attachments']:
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
				{"role": "system", "content": "Describe the attached image(s) objectively and thoroughly. Format: [Brief summary in one sentence], then detailed description of visual elements. Do not ask questions or offer help."},
				{"role": "user", "content": [
					{"type": "text", "text": "Describe these images in detail."},
					*[{"type": "image_url", "image_url": {"url": att.url}} for att in images]
				]}
			]
		)
		return resp
	return ""

def create_message(msg: discord.Message):
	return {"name": msg.author.name, "a_id": msg.author.id, "content": msg.content, "attachments": msg.attachments, "time": int(msg.created_at.timestamp())}

async def ask(content: str, memory: str, channel: discord.TextChannel, max_depth: int = 5) -> str:
	"""
	Recursively execute tool calls until Algorithm stops requesting tools or max depth reached.
	Returns final content to send to Discord.
	"""
	if max_depth <= 0:
		return content + "\n\n(reached max tool depth, stopping)"
	
	if content.endswith("call none"):
		return

	result = tool.search(content)
	if not result:
		return content
	
	name = result.group(1)
	args = result.group(2)
	content_before_call = content[:result.start()]
	
	if content_before_call.strip():
		await channel.send(content_before_call)
	
	short_term_memory.append({
		"name": "The Algorithm",
		"a_id": bot.user.id,
		"content": content,
		"attachments": [],
		"time": time.time()
	})
	
	if name in functions:
		try:
			if args:
				tool_result = functions[name]["function"](*args.split(","))
			else:
				tool_result = functions[name]["function"]()
			if inspect.isawaitable(tool_result):
				tool_result = await tool_result
		except Exception as e:
			tool_result = f"Error: {str(e)}"
		
		if tool_result == "system:_none":
			return

		short_term_memory.append({
			"name": "system:tool_call",
			"a_id": 0,
			"content": tool_result,
			"attachments": [],
			"time": time.time()
		})
		
		data = await get_messages(memory)
		resp = await ai.chat.completions.create(
			model="gpt-5-chat",
			messages=data["messages"],
			temperature=1.2
		)
		new_content = resp.choices[0].message.content
		print(f"AI (after {name}): {new_content}")
		
		return await ask(new_content, memory, channel, max_depth - 1)
	else:
		return content_before_call + f"\n\n(tried to call non-existent tool: {name})"

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
		tools.current_bot = bot
	except Exception as e:
		print("Sync failed:", e)

@bot.event
async def on_message(message: discord.Message):
	global message_counter
	if message.author.bot or message.author == bot.user or message.channel.id not in [1428968893111865384]:
		return

	try:
		short_term_memory.append(create_message(message))
		memory = format_memory_naturally(load_memory())
		print(f"\n{message.author.name}: {message.content}")
		data = await get_messages(memory)
		tools.current_message = message

		async with message.channel.typing():
			if data["serkan"]:
				resp, desc = await asyncio.gather(
					serkan.chat.completions.create(model="gpt-5-nano", messages=data["messages"]),
					describe_image(message)
				)
				short_term_memory[-1]['attachments'] = []
				short_term_memory[-1]['content'] += f"\nAttached images:\n{desc.choices[0].message.content}"
			else:
				resp = await ai.chat.completions.create(
					model="gpt-5-chat",
					messages=data["messages"],
					temperature=1.2
				)
		
		content = resp.choices[0].message.content
		print("AI: " + content)

		# Handle recursive tool calls
		final_content = await ask(content, memory, message.channel)

		# Send final message
		sent_message = await message.channel.send(final_content)
		short_term_memory.append(create_message(sent_message))
		
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
		raise

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