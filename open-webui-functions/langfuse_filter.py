"""
title: Langfuse Filter
author: open-webui (modified for in-process use)
date: 2026-02-26
version: 1.0.0
license: MIT
description: A filter that traces all LLM calls to LangFuse for observability.
requirements: langfuse>=3.0.0
"""

from typing import List, Optional
import os
import uuid
import json

from pydantic import BaseModel


def get_last_assistant_message(messages: List[dict]) -> str:
    for message in reversed(messages):
        if message["role"] == "assistant":
            return message.get("content", "")
    return ""


def get_last_assistant_message_obj(messages: List[dict]) -> dict:
    for message in reversed(messages):
        if message["role"] == "assistant":
            return message
    return {}


class Filter:
    class Valves(BaseModel):
        pipelines: List[str] = ["*"]
        priority: int = 0
        secret_key: str = ""
        public_key: str = ""
        host: str = "https://us.cloud.langfuse.com"
        debug: bool = False

    def __init__(self):
        self.type = "filter"
        self.name = "Langfuse Filter"
        self.valves = self.Valves(
            **{
                "secret_key": os.getenv("LANGFUSE_SECRET_KEY", ""),
                "public_key": os.getenv("LANGFUSE_PUBLIC_KEY", ""),
                "host": os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
                "debug": os.getenv("LANGFUSE_DEBUG", "false").lower() == "true",
            }
        )
        self.langfuse = None
        self.chat_traces = {}
        self.model_names = {}

    def log(self, message: str):
        if self.valves.debug:
            print(f"[LangFuse] {message}")

    async def on_startup(self):
        self._init_langfuse()

    async def on_valves_updated(self):
        self._init_langfuse()

    def _init_langfuse(self):
        try:
            from langfuse import Langfuse

            self.langfuse = Langfuse(
                secret_key=self.valves.secret_key,
                public_key=self.valves.public_key,
                host=self.valves.host,
                debug=self.valves.debug,
            )
            self.langfuse.auth_check()
            self.log(f"Connected to {self.valves.host}")
        except Exception as e:
            self.log(f"Init failed: {e}")
            self.langfuse = None

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.langfuse:
            self._init_langfuse()
        if not self.langfuse:
            return body

        metadata = body.get("metadata", {})
        chat_id = metadata.get("chat_id") or str(uuid.uuid4())

        if chat_id == "local":
            session_id = metadata.get("session_id")
            chat_id = f"temporary-session-{session_id}"

        # Store chat_id back so outlet can find it
        metadata["chat_id"] = chat_id
        body["metadata"] = metadata

        model_id = body.get("model", "unknown")
        model_info = metadata.get("model", {})
        model_name = model_info.get("name", model_id) if isinstance(model_info, dict) else model_id
        self.model_names[chat_id] = {"id": model_id, "name": model_name}

        user_email = __user__.get("email") if __user__ else None

        self.log(f"INLET chat_id={chat_id} model={model_id} user={user_email}")

        if chat_id not in self.chat_traces:
            try:
                trace = self.langfuse.start_span(
                    name=f"chat:{chat_id}",
                    input=body.get("messages", []),
                    metadata={"interface": "open-webui", "user_id": user_email},
                )
                trace.update_trace(
                    user_id=user_email,
                    session_id=chat_id,
                    tags=["open-webui"],
                    input=body.get("messages", []),
                )
                self.chat_traces[chat_id] = trace
                self.log(f"Created trace for {chat_id}")
            except Exception as e:
                self.log(f"Failed to create trace: {e}")
                return body
        else:
            self.log(f"Reusing trace for {chat_id}")

        # Log user input
        try:
            trace = self.chat_traces[chat_id]
            span = trace.start_span(
                name=f"user_input:{uuid.uuid4()}",
                input=body.get("messages", []),
                metadata={"type": "user_input", "user_id": user_email},
            )
            span.end()
        except Exception as e:
            self.log(f"Failed to log input: {e}")

        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.langfuse:
            self._init_langfuse()
        if not self.langfuse:
            return body

        metadata = body.get("metadata", {})
        chat_id = body.get("chat_id") or metadata.get("chat_id")

        if chat_id == "local":
            session_id = body.get("session_id") or metadata.get("session_id")
            chat_id = f"temporary-session-{session_id}"

        self.log(f"OUTLET chat_id={chat_id}")

        if chat_id not in self.chat_traces:
            self.log(f"No trace for {chat_id}, skipping")
            return body

        trace = self.chat_traces[chat_id]
        assistant_message = get_last_assistant_message(body.get("messages", []))
        assistant_message_obj = get_last_assistant_message_obj(body.get("messages", []))

        # Extract token usage from assistant message or top-level usage
        usage = None
        if assistant_message_obj:
            info = assistant_message_obj.get("usage", {})
            if isinstance(info, dict):
                input_tokens = info.get("prompt_eval_count") or info.get("prompt_tokens")
                output_tokens = info.get("eval_count") or info.get("completion_tokens")
                if input_tokens is not None and output_tokens is not None:
                    usage = {"input": input_tokens, "output": output_tokens, "unit": "TOKENS"}
                    self.log(f"Tokens: {input_tokens} in / {output_tokens} out")

        # Update trace with response
        trace.update_trace(output=assistant_message)

        # Create LLM generation span
        model_id = self.model_names.get(chat_id, {}).get("id", "unknown")
        try:
            usage_details = None
            if usage:
                usage_details = {
                    "input": usage["input"],
                    "output": usage["output"],
                }
            generation = trace.start_generation(
                name=f"llm_response:{uuid.uuid4()}",
                model=model_id,
                input=body.get("messages", []),
                output=assistant_message,
                metadata={"type": "llm_response", "interface": "open-webui"},
                usage_details=usage_details,
            )
            generation.end()
            self.log(f"Generation logged for {chat_id}")
        except Exception as e:
            self.log(f"Failed to log generation: {e}")

        # Flush
        try:
            self.langfuse.flush()
            self.log("Flushed to LangFuse")
        except Exception as e:
            self.log(f"Flush failed: {e}")

        return body
