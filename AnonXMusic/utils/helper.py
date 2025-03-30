from functools import lru_cache
import time

chat_cache = {}
CHAT_CACHE_TTL = 60*60*12

async def get_chat_cached(app, chat_id):
    current_time = time.time()
    
    if chat_id in chat_cache:
        cache_time, chat_data = chat_cache[chat_id]
        if current_time - cache_time < CHAT_CACHE_TTL:
            return chat_data
    
    chat_data = await app.get_chat(chat_id)
    chat_cache[chat_id] = (current_time, chat_data)
    return chat_data