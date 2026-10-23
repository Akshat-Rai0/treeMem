"""Background Auto-Summarizer (Option B) for TreeMem.

Provides server-side automatic compression of dirty nodes in bottom-up topological order,
enforcing length caps, child list matching, and privacy leakage checks with validation retries.
"""

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from treemem.tree_manager import TreeManager, norm_path

logger = logging.getLogger("treemem.auto_compress")


def clean_llm_markdown(text: str) -> str:
    """Strip triple backtick fences if LLM wrapped markdown output in code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```markdown"):
        cleaned = cleaned[11:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


class GroqSummarizerClient:
    """Lightweight Groq API client with key rotation and failover for auto-summaries."""

    def __init__(self, keys: Optional[List[str]] = None, model: str = "qwen/qwen3.8-27b"):
        self.model = model
        self.keys = keys or self._load_keys()
        self.current_idx = 0

    def _load_keys(self) -> List[str]:
        keys = []
        env_path = Path(".env")
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        if k.strip().startswith("GROQ_API_KEY"):
                            cleaned = v.strip().strip("\"'")
                            if cleaned:
                                keys.append(cleaned)
        return keys

    def _get_key(self) -> str:
        if not self.keys:
            raise RuntimeError("No Groq API keys found in .env for AutoCompressor.")
        key = self.keys[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        return key

    def generate(self, system_prompt: str, user_prompt: str, max_retries: int = 4) -> str:
        """Call Groq chat completion with multi-key failover."""
        last_error = None
        for attempt in range(max_retries):
            key = self._get_key()
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 300,
            }
            try:
                resp = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                elif resp.status_code == 429:
                    time.sleep(2.0 + attempt)
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    time.sleep(1.0)
            except Exception as e:
                last_error = str(e)
                time.sleep(1.0)

        raise RuntimeError(f"Groq auto-summarizer failed after {max_retries} attempts: {last_error}")


class AutoCompressor:
    """
    Manages automated compression of dirty nodes bottom-up.
    Validates output through commit_summary() and supports background daemon worker.
    """

    def __init__(
        self,
        tree_manager: TreeManager,
        llm_caller: Optional[Callable[[str, str], str]] = None,
        model: str = "qwen/qwen3.8-27b",
    ):
        self.mgr = tree_manager
        self.model = model
        if llm_caller:
            self.llm_caller = llm_caller
        else:
            client = GroqSummarizerClient(model=model)
            self.llm_caller = client.generate

        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def build_compression_prompt(self, path: str) -> Tuple[str, str]:
        """Construct system and user prompts for compressing a given node."""
        clean = norm_path(path)
        compress_info = self.mgr.compress(clean)
        node = self.mgr.store.read_node(clean)
        node_name = node.name if node else (clean.split("/")[-1] or "root")

        system_prompt = (
            "You are an expert memory summarizer for a hierarchical knowledge tree.\n"
            "Your task is to write a concise, high-level summary of the topic.\n"
            "STRICT RULES:\n"
            "1. Length: Target 40 to 100 tokens. STRICT MAXIMUM is 150 tokens.\n"
            "2. If children subtopics exist, you MUST include a '## Children' section listing every child exactly:\n"
            "   - [[child_label]] - teaser description\n"
            "3. If a child is marked sensitivity: private, its teaser MUST strictly be: 'contains private details, expand to view'.\n"
            "4. NEVER leak confidential words, tokens, or facts from private children into the summary.\n"
            "5. Output ONLY the raw markdown content. No markdown code blocks."
        )

        user_content_lines = [
            f"Topic: {node_name} (path: '{clean or '/'}')",
            f"Required Children: {compress_info['required_children']}",
            "\nInput Source Data:",
        ]

        for item in compress_info["inputs"]:
            if item["type"] == "fact":
                user_content_lines.append(f"- Fact: {item['text']} (id: {item['entry_id']})")
            elif item["type"] == "child_summary":
                sens_note = " [PRIVATE]" if item.get("sensitivity") == "private" else ""
                user_content_lines.append(
                    f"- Child '{item['label']}'{sens_note}: {item.get('summary', '')}"
                )

        user_content_lines.append(
            "\nPlease produce the summary markdown with frontmatter name and ## Children list."
        )
        user_prompt = "\n".join(user_content_lines)

        return system_prompt, user_prompt

    def compress_node(self, path: str, max_retries: int = 2) -> Dict[str, Any]:
        """
        Compress a single node using LLM with validation-retry loop.
        Returns commit result dict.
        """
        clean = norm_path(path)
        node = self.mgr.store.read_node(clean)
        if not node:
            return {"ok": False, "error": f"Node '{clean or '/'}' not found"}

        system_prompt, user_prompt = self.build_compression_prompt(clean)

        for attempt in range(max_retries + 1):
            try:
                raw_summary = self.llm_caller(system_prompt, user_prompt)
            except Exception as e:
                return {"ok": False, "error": f"LLM generation failed: {e}", "path": clean}

            summary_text = clean_llm_markdown(raw_summary)

            # Ensure frontmatter exists if LLM omitted it
            if not summary_text.startswith("---"):
                child_dirs = self.mgr.store.list_child_dirs(clean)
                fm_header = f"---\nname: {node.name}\ndirty: false\n---\n"
                summary_text = fm_header + summary_text

            # Validate and commit atomically
            commit_res = self.mgr.commit_summary(clean, summary_text, session="auto_compress")
            if commit_res.get("ok"):
                return {
                    "ok": True,
                    "path": clean or "/",
                    "tokens": commit_res.get("tokens", 0),
                    "attempts": attempt + 1,
                }

            # Validation failed, construct retry prompt with specific error
            error_msg = commit_res.get("error", "Unknown validation error")
            user_prompt += (
                f"\n\n[RETRY FEEDBACK] Your previous summary was rejected with error:\n"
                f"{error_msg}\n"
                f"Please fix this exact issue and regenerate a compliant summary."
            )

        return {"ok": False, "error": error_msg, "path": clean or "/", "attempts": max_retries + 1}

    def compress_all_dirty(self) -> Dict[str, Any]:
        """
        Compress all dirty nodes in the vault in bottom-up order (deepest leaves first).
        """
        dirty_nodes = self.mgr.get_dirty_nodes()
        if not dirty_nodes:
            return {
                "ok": True,
                "cleaned_count": 0,
                "cleaned_nodes": [],
                "errors": [],
                "message": "Vault is clean. No dirty nodes to compress.",
            }

        cleaned = []
        errors = []

        for p in dirty_nodes:
            res = self.compress_node(p)
            if res.get("ok"):
                cleaned.append({"path": p, "tokens": res.get("tokens", 0), "attempts": res.get("attempts", 1)})
            else:
                errors.append({"path": p, "error": res.get("error")})

        return {
            "ok": len(errors) == 0,
            "cleaned_count": len(cleaned),
            "cleaned_nodes": cleaned,
            "error_count": len(errors),
            "errors": errors,
        }

    def start_background_worker(self, interval_seconds: float = 30.0) -> None:
        """Start a background daemon thread that periodically compresses dirty nodes."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()

        def _worker_loop():
            logger.info("AutoCompressor background worker started.")
            while not self._stop_event.is_set():
                try:
                    dirty = self.mgr.get_dirty_nodes()
                    if dirty:
                        logger.info(f"AutoCompressor found {len(dirty)} dirty nodes. Compressing...")
                        self.compress_all_dirty()
                except Exception as e:
                    logger.error(f"Error in AutoCompressor background loop: {e}")

                self._stop_event.wait(interval_seconds)
            logger.info("AutoCompressor background worker stopped.")

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="TreeMem-AutoCompressor")
        self._worker_thread.start()

    def stop_background_worker(self) -> None:
        """Stop the background daemon thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=3.0)
            self._worker_thread = None
