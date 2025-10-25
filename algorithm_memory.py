from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict
import json, os, traceback
from pathlib import Path
from openai import AsyncOpenAI
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
MEMORY_FILE = Path(os.getenv("MEMORY_FILE", "memory.json"))
ai = AsyncOpenAI(api_key=os.getenv("API_KEY"), base_url="https://api.llm7.io/v1")
SYSTEM_PROMPT = ""
with open(os.getenv("MEMORY_PROMPT"), encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

class BotIdentity(BaseModel):
	model_config = ConfigDict(extra="forbid")
	personality_traits: list[str] = Field(default_factory=list)
	beliefs: list[str] = Field(default_factory=list)
	background_facts: list[str] = Field(default_factory=list)
	preferences: list[str] = Field(default_factory=list)
	mood_notes: list[str] = Field(default_factory=list)

class UserMemory(BaseModel):
	model_config = ConfigDict(extra="forbid")
	user_id: str
	current_username: str
	preferred_name: Optional[str] = None
	previous_usernames: list[str] = Field(default_factory=list)
	possibly_aka: Optional[str] = None
	facts: list[str] = Field(default_factory=list)
	preferences: list[str] = Field(default_factory=list)
	projects: list[str] = Field(default_factory=list)
	personality_notes: list[str] = Field(default_factory=list)

class ConversationContext(BaseModel):
	model_config = ConfigDict(extra="forbid")
	current_topic: str = ""
	ongoing_jokes: list[str] = Field(default_factory=list)
	emotional_tone: str = ""

class MemoryBank(BaseModel):
	model_config = ConfigDict(extra="forbid")
	bot_identity: BotIdentity = Field(default_factory=BotIdentity)
	users: Dict[str, UserMemory] = Field(default_factory=dict)
	conversation_context: ConversationContext = Field(default_factory=ConversationContext)
	recent_summary: str = ""
	historical_context: str = ""

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
_supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def load_memory() -> MemoryBank:
    """
    Load memory from Supabase if configured, otherwise fall back to local file.
    """
    if _supabase:
        try:
            res = _supabase.table("memories").select("data").eq("key", "memory").limit(1).execute()
            if getattr(res, "error", None):
                print("Supabase load error:", res.error)
                return MemoryBank()
            data_list = getattr(res, "data", None) or []
            if data_list:
                # data is stored in the `data` JSONB column
                row = data_list[0]
                if isinstance(row, dict) and "data" in row and row["data"] is not None:
                    return MemoryBank(**row["data"])
            return MemoryBank()
        except Exception as e:
            print("Supabase load exception:", repr(e))
            return MemoryBank()
    # fallback to local file
    if MEMORY_FILE.exists():
        return MemoryBank(**json.loads(MEMORY_FILE.read_text(encoding="utf-8")))
    return MemoryBank()

def save_memory(memory: MemoryBank):
    """
    Save memory to Supabase if configured, otherwise write to local file.
    Uses upsert so the single row with key="memory" is created/updated.
    """
    if _supabase:
        try:
            payload = {"key": "memory", "data": memory.model_dump()}
            res = _supabase.table("memories").upsert(payload).execute()
            if getattr(res, "error", None):
                raise RuntimeError(f"Supabase save error: {res.error}")
            return
        except Exception as e:
            raise
    # fallback to local file
    MEMORY_FILE.write_text(memory.model_dump_json(indent=2), encoding="utf-8")

async def update_memory_bank(recent_messages: list, current_memory: MemoryBank, bot_user_id: str) -> MemoryBank:
    # Guard against None being passed in
    recent_messages = list(recent_messages or [])

    formatted_messages = "\n".join(
        f"{getattr(m.author, 'name', getattr(m.author, 'global_name', '<unknown>'))} (ID: {getattr(m.author, 'id', '<no-id>')}): {getattr(m, 'content', '')}" 
        for m in recent_messages
    )

    system_prompt = SYSTEM_PROMPT.format(bot_user_id=bot_user_id)
    user_prompt = f"""Current Memory:
{current_memory.model_dump_json(indent=2)}

Recent Messages:
{formatted_messages}

Update the memory bank with any new information. Return only the JSON object described above."""

    # Try letting the SDK parse directly into the Pydantic model first.
    try:
        response = await ai.responses.parse(
            model="gpt-5-chat",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=MemoryBank,
        )
        return response.output_parsed
    except Exception:
        # Fallback: request raw response and validate into the Pydantic model manually
        resp = await ai.responses.create(
            model="gpt-5-chat",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        # Try to extract JSON text in a robust manner
        raw = None
        try:
            out = getattr(resp, "output", None)
            if out and isinstance(out, list) and len(out) > 0:
                first = out[0]
                if isinstance(first, dict):
                    content = first.get("content") or []
                    if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict):
                        raw = content[0].get("text")
                else:
                    # SDK objects sometimes expose .content as object list
                    try:
                        raw = first.content[0].text
                    except Exception:
                        raw = None
        except Exception:
            raw = None

        if not raw:
            raw = extract_text(resp)

        if not raw:
            raise ValueError("No text found in model response to parse into MemoryBank")

        # Validate / parse into MemoryBank (will raise useful errors if invalid)
        return MemoryBank.model_validate_json(raw)

def extract_text(resp):
    texts = []
    for item in (getattr(resp, "output") or []):
        # support both dict-like and object-like shapes
        if isinstance(item, dict):
            parts = item.get("content") or []
        else:
            parts = getattr(item, "content", []) or []
        for part in parts:
            if isinstance(part, dict):
                # prefer explicit text pieces
                t = part.get("text")
                if t:
                    texts.append(t)
            else:
                t = getattr(part, "text", None)
                if t:
                    texts.append(t)
    return "".join(texts)

async def update_memory_bank_safe(recent_messages: list, current_memory: MemoryBank, bot_user_id: str) -> MemoryBank:
    """
    Wrap update_memory_bank in try/except to catch and log exceptions.
    """
    try:
        return await update_memory_bank(recent_messages, current_memory, bot_user_id)
    except Exception as e:
        print("Exception inside update_memory_bank:", repr(e))
        print(traceback.format_exc())
        raise

async def background_memory_update(messages, bot_user_id: str):
    memory = load_memory()
    updated_memory = await update_memory_bank_safe(messages, memory, bot_user_id)
    try:
        save_memory(updated_memory)
    except Exception as e:
        raise
    return updated_memory

def format_memory_naturally(memory: MemoryBank) -> str:
	parts = []
	
	# Bot's own identity
	if memory.bot_identity.background_facts or memory.bot_identity.beliefs or memory.bot_identity.personality_traits:
		parts.append("About yourself:")
		if memory.bot_identity.personality_traits:
			parts.append(f"- Traits: {', '.join(memory.bot_identity.personality_traits)}")
		if memory.bot_identity.background_facts:
			parts.append(f"- Background: {', '.join(memory.bot_identity.background_facts)}")
		if memory.bot_identity.beliefs:
			parts.append(f"- Beliefs/opinions: {', '.join(memory.bot_identity.beliefs)}")
		if memory.bot_identity.preferences:
			parts.append(f"- Preferences: {', '.join(memory.bot_identity.preferences)}")
	
	# User memories
	if memory.users:
		parts.append("\nPeople you know:" if parts else "People you know:")
		for uid, u in memory.users.items():
			name = u.preferred_name or u.current_username
			facts = ", ".join(u.facts) if u.facts else "no specific facts yet"
			parts.append(f"- {name} (@{u.current_username}): {facts}")
	
	# Current context
	if memory.conversation_context.current_topic:
		parts.append(f"\nCurrent topic: {memory.conversation_context.current_topic}")
	
	if memory.conversation_context.ongoing_jokes:
		parts.append(f"Ongoing jokes: {', '.join(memory.conversation_context.ongoing_jokes)}")
	
	# Summary
	if memory.recent_summary:
		parts.append(f"\nRecent context: {memory.recent_summary}")
	if memory.historical_context:
		parts.append(f"Long-term context: {memory.historical_context}")
	
	return "\n".join(parts)