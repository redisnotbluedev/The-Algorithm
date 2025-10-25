import vercel_blob.blob_store as blob_client
from typing import Optional
import asyncio, os

async def upload(image_bytes: bytes, filename: str) -> Optional[str]:
	"""Uploads the image to Vercel Blob Storage and returns the public URL."""
	
	if not blob_client:
		print("Vercel Blob Client is not initialized. Cannot upload.")
		return None
	
	try:
		unique_filename = f"discord-uploads/{os.urandom(8).hex()}_{filename}"
		use_multipart = len(image_bytes) > 4 * 1024 * 1024 # > 4MB

		resp = await asyncio.to_thread(
			blob_client.put,
			unique_filename,
			image_bytes,
			multipart=use_multipart
		)

		return resp.get('url')

	except Exception as e:
		print(f"Vercel Blob upload failed for file '{filename}': {e}")
		return None