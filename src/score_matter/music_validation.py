"""Per-read ancestry validation; never retain asset checks between operations."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from matter_audio_core.errors import AudioError


MAX_ANCESTRY = 32
_STATE = ContextVar("score_music_validation", default=None)


@contextmanager
def validation_scope():
    token = None
    if _STATE.get() is None:
        token = _STATE.set({"active": set(), "cache": {}, "frames": [], "derived_depth": 0})
    try:
        yield
    finally:
        if token is not None:
            _STATE.reset(token)


@contextmanager
def derived_annotation_level():
    with validation_scope():
        state = _STATE.get()
        if state["derived_depth"] >= MAX_ANCESTRY:
            raise AudioError("music_annotation_ancestry", "Derived annotation ancestry exceeds 32 active levels")
        state["derived_depth"] += 1
        try:
            yield
        finally:
            state["derived_depth"] -= 1


def checked_asset(kind):
    def decorate(function):
        @wraps(function)
        def checked(store, asset_id):
            with validation_scope():
                state = _STATE.get()
                key = (str(store.root), kind, asset_id)
                if key in state["active"]:
                    raise AudioError("music_annotation_ancestry", "Musical asset ancestry contains a cycle")
                if key in state["cache"]:
                    result, depth = state["cache"][key]
                else:
                    frame = {"child_depth": 0}
                    state["frames"].append(frame)
                    state["active"].add(key)
                    try:
                        result = function(store, asset_id)
                        own_depth = int(kind == "annotation" and result[1]["schema"] == "score-music-arrangement-annotation/v1")
                        depth = own_depth + frame["child_depth"]
                        state["cache"][key] = (result, depth)
                    finally:
                        state["active"].remove(key)
                        state["frames"].pop()
                # A subtree cached on a shallow branch must still fit when reused
                # deeper in the same DAG; caching cannot bypass the depth bound.
                if state["derived_depth"] + depth > MAX_ANCESTRY:
                    raise AudioError("music_annotation_ancestry", "Derived annotation ancestry exceeds 32 active levels")
                if state["frames"]:
                    parent = state["frames"][-1]
                    parent["child_depth"] = max(parent["child_depth"], depth)
                return result
        return checked
    return decorate
