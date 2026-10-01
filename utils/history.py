import hashlib
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .state import load_persistent_state, save_persistent_state


def make_state_key(directory, pattern, recursive, sort_by) -> str:
    """Generate a stable hash for a workflow configuration."""
    h = hashlib.md5()
    h.update(str(directory).encode())
    h.update(str(pattern).encode())
    h.update(str(recursive).encode())
    h.update(str(sort_by).encode())
    return h.hexdigest()


def is_fallback_marker(entry: str) -> bool:
    """Check if an entry is a fallback tensor marker."""
    return entry.startswith("fallback::")


def make_fallback_marker(sig: str) -> str:
    """Create a fallback marker string from a tensor signature."""
    return f"fallback::{sig}"


@dataclass
class HistoryState:
    """Persistent history of resolved outputs for one workflow configuration."""

    key: str
    history: List[str] = field(default_factory=list)
    last_fb_sig: Optional[str] = None
    global_counter: int = 0

    @classmethod
    def load(cls, key: str) -> "HistoryState":
        raw = load_persistent_state(key)
        return cls(
            key=key,
            history=raw.get("history", []),
            last_fb_sig=raw.get("last_fb_sig"),
            global_counter=raw.get("global_counter", 0),
        )

    def save(self) -> None:
        save_persistent_state(
            self.key,
            {
                "history": self.history,
                "last_fb_sig": self.last_fb_sig,
                "global_counter": self.global_counter,
            },
        )

    def reset_for_tensor(self, sig: str) -> None:
        self.history = [make_fallback_marker(sig)]
        self.last_fb_sig = sig
        self.global_counter = 1
        self.save()

    def append_entry(self, entry: str, sig: str) -> int:
        self.history.append(entry)
        self.global_counter = len(self.history)
        self.last_fb_sig = sig
        self.save()
        return self.global_counter

    def pick_new_entry(
        self, picker: Callable[[], Optional[str]], fallback_sig: str
    ) -> str:
        picked = picker()
        if picked is not None:
            return picked
        return make_fallback_marker(fallback_sig)
