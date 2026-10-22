import asyncio
import logging
import re

from google import genai
from google.genai import errors

from src.config.settings import get_settings

logger = logging.getLogger("ai_service")
settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)

RETRYABLE_CODES = [429, 500, 503, 504]


def get_wait_seconds(error, attempt):
    """Google's 429 message often says 'retry in 54s'. Use that number if it is there."""
    message = str(error)
    match = re.search(r"retry in ([\d.]+)s", message)

    if match is not None:
        seconds = float(match.group(1)) + 1
        if seconds > 60:
            seconds = 60.0
        return seconds

    return 5.0 * (attempt + 1)


async def generate_text(prompt):
    """Ask Gemini for text. Retries, and switches to the backup model if one is set."""
    models_to_try = [settings.GEMINI_MODEL]

    backup_model = settings.GEMINI_FALLBACK_MODEL
    if backup_model != "" and backup_model != settings.GEMINI_MODEL:
        models_to_try.append(backup_model)

    last_error = None

    for model_index in range(len(models_to_try)):
        model_name = models_to_try[model_index]
        is_last_model = model_index == len(models_to_try) - 1

        for attempt in range(2):
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response.text is None:
                    return ""
                return response.text

            except errors.APIError as error:
                error_code = getattr(error, "code", None)

                if error_code not in RETRYABLE_CODES:
                    raise

                last_error = error
                logger.warning("%s failed with code %s (attempt %d/2)", model_name, error_code, attempt + 1)
                if not is_last_model:
                    break
                if attempt == 1:
                    break
                wait_seconds = get_wait_seconds(error, attempt)
                await asyncio.sleep(wait_seconds)

    if last_error is None:
        raise RuntimeError("Gemini returned no response")
    raise last_error