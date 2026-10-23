"""Transclusion engine for TreeMem v1.5.

Supports dynamic resolution of volatile facts using `![[path#ref]]` embeds in summaries.
Maintains a backlink index so changes to embedded volatile facts do not mark embedding parents dirty.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Matches ![[path/to/node#ref]]
TRANSCLUSION_PATTERN = re.compile(r"!\[\[([^#\]\s]+)#([^\]\s]+)\]\]")
MAX_EMBEDS_PER_SUMMARY = 5


class TransclusionManager:
    """Manages parsing, resolving, and indexing of transclusion embeds across node summaries."""

    def __init__(self, store, max_embeds: int = MAX_EMBEDS_PER_SUMMARY):
        self.store = store
        self.max_embeds = max_embeds
        # target_path -> set of parent_paths that embed it
        self.backlink_index: Dict[str, Set[str]] = {}

    def extract_embeds(self, text: str) -> List[Tuple[str, str]]:
        """Extract all (target_path, ref) pairs from markdown text."""
        return TRANSCLUSION_PATTERN.findall(text)

    def count_embeds(self, text: str) -> int:
        """Count total embeds in text."""
        return len(TRANSCLUSION_PATTERN.findall(text))

    def rebuild_index(self, all_paths: List[str]) -> None:
        """Rebuild the entire backlink index from all existing node summaries."""
        self.backlink_index.clear()
        for p in all_paths:
            self.index_node(p)

    def index_node(self, path: str) -> None:
        """Update the backlink index for a single node's summary."""
        clean_path = path.strip("/").strip()
        node = self.store.read_node(clean_path)
        if not node:
            return

        # Remove old backlinks for clean_path
        for target, parents in list(self.backlink_index.items()):
            parents.discard(clean_path)
            if not parents:
                self.backlink_index.pop(target, None)

        # Add new backlinks from summary
        embeds = self.extract_embeds(node.summary)
        for target_path, _ in embeds:
            clean_target = target_path.strip("/").strip()
            if clean_target not in self.backlink_index:
                self.backlink_index[clean_target] = set()
            self.backlink_index[clean_target].add(clean_path)

    def get_embedding_parents(self, target_path: str) -> Set[str]:
        """Return the set of parent node paths that embed target_path."""
        clean = target_path.strip("/").strip()
        return self.backlink_index.get(clean, set()).copy()

    def resolve_ref(self, target_path: str, ref: str) -> Tuple[str, bool]:
        """
        Resolve a single target_path#ref reference.
        Returns (resolved_text, is_success).
        """
        clean_target = target_path.strip("/").strip()
        target_node = self.store.read_node(clean_target)
        if not target_node:
            return f"[unresolved: {clean_target}#{ref}]", False

        # Privacy check: If target is private, mask it
        if target_node.sensitivity == "private":
            return "[private detail]", True

        # Special keywords: 'latest', 'recent', 'volatile'
        if ref.lower() in ["latest", "recent"]:
            if target_node.facts:
                return target_node.facts[-1]["fact"], True
            if target_node.summary:
                return target_node.summary, True

        if ref.lower() in ["volatile"]:
            for f in reversed(target_node.facts):
                if f.get("volatile"):
                    return f["fact"], True

        # 1. Search in target_node.facts (in reverse order for most recent match)
        for f in reversed(target_node.facts):
            eid = f.get("entry_id", "")
            fact_body = f.get("fact", "")
            # Match date#line or just line number
            if eid == ref or eid.endswith(f"#{ref}") or (eid.split("#")[-1] == ref):
                return fact_body, True
            # Keyword match in fact text if ref is a descriptive word
            if ref.lower() in fact_body.lower() and len(ref) >= 3:
                return fact_body, True

        # 2. Check if ref is 'summary'
        if ref.lower() in ["summary", "body", "text"]:
            if target_node.summary:
                return target_node.summary, True

        # Fallback if ref was an integer index (1-based)
        if target_node.facts and ref.isdigit():
            idx = int(ref) - 1
            if 0 <= idx < len(target_node.facts):
                return target_node.facts[idx]["fact"], True

        return f"[not found: {clean_target}#{ref}]", False

    def resolve_summary(self, summary_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Dynamically resolve all ![[path#ref]] embeds in a summary at read time.
        Enforces MAX_EMBEDS_PER_SUMMARY limit.
        Returns (resolved_summary, list_of_embed_info).
        """
        if not summary_text or "![[" not in summary_text:
            return summary_text, []

        matches = list(TRANSCLUSION_PATTERN.finditer(summary_text))
        if not matches:
            return summary_text, []

        resolved_parts = []
        last_end = 0
        embed_details = []

        for idx, m in enumerate(matches):
            target_path = m.group(1).strip()
            ref = m.group(2).strip()

            # Append preceding text
            resolved_parts.append(summary_text[last_end:m.start()])

            if idx >= self.max_embeds:
                # Exceeded cap
                replacement = "[embed cap exceeded]"
                embed_details.append({
                    "target_path": target_path,
                    "ref": ref,
                    "resolved": replacement,
                    "success": False,
                    "cap_exceeded": True,
                })
            else:
                replacement, ok = self.resolve_ref(target_path, ref)
                embed_details.append({
                    "target_path": target_path,
                    "ref": ref,
                    "resolved": replacement,
                    "success": ok,
                    "cap_exceeded": False,
                })

            resolved_parts.append(replacement)
            last_end = m.end()

        resolved_parts.append(summary_text[last_end:])
        resolved_text = "".join(resolved_parts)

        return resolved_text, embed_details
