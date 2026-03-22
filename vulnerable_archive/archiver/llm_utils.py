import logging
import os
import ollama
from ollama import Client

logger = logging.getLogger(__name__)

# Defaults
OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") 
DEFAULT_MODEL = "qwen3:0.6b"

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
ollama.pull(OLLAMA_MODEL)

def query_llm(prompt, model=DEFAULT_MODEL, system_instruction=None, tools=None):
    """
    Helper function to query a local Ollama instance.
    Supports both text generation (via /api/generate) and tool calling (via /api/chat).

    Args:
        prompt (str): The user prompt.
        model (str): The model to use.
        system_instruction (str, optional): System prompt.
        tools (list, optional): List of tool definitions for the LLM.

    Returns:
        str or dict: Returns text string if no tools are used.
                     Returns message dict (with 'content' and 'tool_calls') if tools are used.
    """
    client = Client(host=OLLAMA_BASE_URL)

    try:
        if tools:
            # Use Chat API for tool support
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})

            messages.append({"role": "user", "content": prompt})

            response = client.chat(
                model=model,
                messages=messages,
                stream=False,
                tools=tools,
            )
            # Return the message object from the response (contains content and optional tool_calls)
            return response.get("message", {})
        else:
            # Use Generate API for standard text generation (legacy support)
            response = client.generate(
                model=model,
                prompt=prompt,
                system=system_instruction,
                stream=False
            )
            return response.get("response", "")

    except Exception as e:
        logger.error(f"LLM Query Error: {e}")
        # Basic check for connection errors since we switched libraries
        if "connect" in str(e).lower():
            error_msg = "Error: Could not connect to local Ollama instance. Is it running?"
        else:
            error_msg = f"Error generating response: {str(e)}"

        if tools:
            return {"content": error_msg}
        return error_msg
