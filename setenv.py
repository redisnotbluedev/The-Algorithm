from pathlib import Path
import re, os

DEFAULT_ENV_PATH = Path(".env")

def set_value(key: str, value: str, env_path: Path = DEFAULT_ENV_PATH):
	"""
	Sets a key-value pair in the .env file and updates the current process environment.

	Args:
		key (str): The environment variable key (e.g., 'API_KEY').
		value (str): The new value for the key.
		env_path (Path): The path to the .env file.
	"""
	key = key.strip()
	# Ensure the value is safe for the .env file (wrap in double quotes)
	value = f'"{value}"'
	new_line = f'{key}={value}\n'
	
	# 1. Read existing lines (or start with an empty list if file doesn't exist)
	lines = []
	if env_path.exists():
		with open(env_path, 'r', encoding='utf-8') as f:
			lines = f.readlines()

	# 2. Check if the key already exists and update the line
	updated = False
	new_lines = []
	pattern = re.compile(f'^{re.escape(key)}=.*', re.IGNORECASE)

	for line in lines:
		if pattern.match(line):
			new_lines.append(new_line)
			updated = True
		else:
			new_lines.append(line)

	# 3. If the key was not found, append it to the end
	if not updated:
		new_lines.append(f"\n{new_line}")

	# 4. Write all lines back to the file
	try:
		with open(env_path, 'w', encoding='utf-8') as f:
			f.writelines(new_lines)
	except Exception as e:
		print(f"ERROR: Could not write to .env file at {env_path}: {e}")
		return

	# 5. Update the running process environment immediately
	os.environ[key] = value.strip('"') 
	print(f"Updated .env and environment for key: {key}")