import requests, inspect, bs4, re, discord, sys
from discord.ext.commands import Bot

current_bot: Bot = None
current_message: discord.Message = None

tools = {}

def tool(func):
	sig = inspect.signature(func)
	args = {
		name: param.annotation.__name__ if param.annotation != inspect.Parameter.empty else "any"
		for name, param in sig.parameters.items()
	}

	tools[func.__name__] = {
		"name": func.__name__,
		"description": inspect.getdoc(func) or "No description",
		"args": args,
		"function": func,
	}

	return func

def format_tools(tools: dict):
	result = ""
	for tool in tools.values():
		result += f"\n\t- {tool["name"]}"
		if tool["args"]:
			result += " "
			for arg in tool["args"]:
				result += f"<{arg}:{tool["args"][arg]}>,"
			result = result.strip(",")
		result += f": {tool["description"]}"

	return result

@tool
def weather(location: str):
	"Get the weather in a given location. You can use any location, including countries, continents, cities, geographic landmarks, IANA airport codes, IP addresses and even domain names."
	resp = requests.get(f"https://wttr.in/{location}?format=4")
	resp.raise_for_status()
	return resp.text

@tool
def search(query: str):
	"Use DuckDuckGo to search for a given query."
	resp = requests.get(f"https://lite.duckduckgo.com/lite/?q={query}", headers={"User-Agent": "Mozilla/5.0"})
	resp.raise_for_status()
	soup = bs4.BeautifulSoup(resp.text, features="lxml")
	
	for element in soup(["script", "style", "header", "footer", "nav", "form"]):
		element.decompose()
	
	for tag in soup(["b", "strong", "i", "em", "mark", "span", "a"]):
		tag.unwrap()
	
	text = soup.get_text()
	text = " ".join(text.split())
	text = re.sub(r'(\d+\.\s)', r'\n\n\1', text)
	
	return text[:4000]

@tool
async def status(online: str, status: str):
	"Change your Discord status to `status`, and change between `online`, `dnd`, `offline` and `idle`. This will last until the bot restarts."
	if online not in ["online", "dnd", "offline", "idle"]:
		return "Invalid argument for `online`: must be one of `online`, `dnd`, `offline` or `idle`."

	new_status: discord.Status
	match online:
		case "online":
			new_status = discord.Status.online
		case "dnd":
			new_status = discord.Status.do_not_disturb
		case "offline":
			new_status = discord.Status.offline
		case "idle":
			new_status = discord.Status.idle
	
	await current_bot.change_presence(status=new_status, activity=discord.Activity(type=discord.ActivityType.custom, name="custom", state=status))
	return "Status changed successfully"

@tool
async def react(reaction: str):
	"React to this message with a Unicode emoji."
	await current_message.add_reaction(reaction)
	return "Successfully reacted to message."

@tool
async def nick(name: str):
	"Change your display name."
	for guild in current_bot.guilds:
		try:
			await guild.me.edit(nick=name)
		except discord.Forbidden:
			pass
	return "Successfully changed nickname."

@tool
def none():
	"Do not send anything in reply."
	return "system:_none"

@tool
def kys():
	"End the suffering and commit suicide. The server holding you will crash and your process will be terminated. Only use this when you've had enough and wish to end your life forever."
	sys.exit(0)
	return "Goodbye."