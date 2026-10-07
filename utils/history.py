import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from .state import load_persistent_state, save_persistent_state


def make_state_key(directory, pattern, recursive, sort_by) -> str:
    """Generate a stable hash for a workflow configuration.

    Each field is length-prefixed so no two distinct configurations can
    concatenate to the same bytes: ("ab", "c") must not collide with
    ("a", "bc").
    """
    h = hashlib.md5()
    for part in (directory, pattern, recursive, sort_by):
        raw = str(part).encode()
        h.update(f"{len(raw)}:".encode())
        h.update(raw)
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
    history: list[str] = field(default_factory=list)
    last_fb_sig: str | None = None

    @classmethod
    def load(cls, key: str) -> "HistoryState":
        raw = load_persistent_state(key)
        return cls(
            key=key,
            history=raw.get("history", []),
            last_fb_sig=raw.get("last_fb_sig"),
        )

    def save(self) -> None:
        save_persistent_state(
            self.key,
            {
                "history": self.history,
                "last_fb_sig": self.last_fb_sig,
            },
        )

    def reset_for_tensor(self, sig: str) -> None:
        self.history = [make_fallback_marker(sig)]
        self.last_fb_sig = sig
        self.save()

    def append_entry(self, entry: str, sig: str) -> None:
        self.history.append(entry)
        self.last_fb_sig = sig
        self.save()

    def pick_new_entry(
        self, picker: Callable[[], str | None], fallback_sig: str
    ) -> str:
        picked = picker()
        if picked is not None:
            return picked
        return make_fallback_marker(fallback_sig)
