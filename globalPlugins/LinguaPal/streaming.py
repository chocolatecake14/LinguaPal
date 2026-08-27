"""Incremental helpers for turning a token stream into speech."""

import re
import wx
import ui


class ThinkFilter:
    """Strips <think>...</think> out of a token stream, incrementally.

    The old _strip_thinking re-ran two regexes over the whole accumulated
    response on every chunk, which is O(n^2) and gets visibly slow on long
    answers, on the very thread that is feeding speech.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self._buf = ""
        self._inside = False

    def feed(self, chunk):
        self._buf += chunk
        out = []
        while self._buf:
            if self._inside:
                i = self._buf.find(self.CLOSE)
                if i == -1:
                    # Discard, but keep a tail in case the tag spans two chunks.
                    if len(self._buf) > len(self.CLOSE):
                        self._buf = self._buf[-len(self.CLOSE):]
                    break
                self._buf = self._buf[i + len(self.CLOSE):]
                self._inside = False
            else:
                i = self._buf.find(self.OPEN)
                if i == -1:
                    keep = len(self.OPEN) - 1
                    if len(self._buf) > keep:
                        out.append(self._buf[:-keep])
                        self._buf = self._buf[-keep:]
                    break
                out.append(self._buf[:i])
                self._buf = self._buf[i + len(self.OPEN):]
                self._inside = True
        return "".join(out)

    def flush(self):
        rest = "" if self._inside else self._buf
        self._buf = ""
        self._inside = False
        return rest


class SpeechStreamer:
    """Speaks a token stream as soon as complete sentences are available.

    eagerFirst shortens time-to-first-audio: the opening utterance may break at
    a word boundary once that many characters have arrived, instead of waiting
    for a full stop a long first sentence might not reach for another second.
    """

    BREAKS = ".!?\n۔؟।"

    def __init__(self, guard=None, eagerFirst=0):
        self._buf = ""
        self._guard = guard
        self._eager = eagerFirst
        self._spoken = False

    def _say(self, text):
        if text and (self._guard is None or self._guard()):
            wx.CallAfter(ui.message, text)
            self._spoken = True

    def feed(self, text):
        self._buf += text
        cut = -1
        for idx, ch in enumerate(self._buf):
            if ch in self.BREAKS:
                cut = idx
        if cut < 0 and not self._spoken and self._eager and len(self._buf) >= self._eager:
            cut = self._buf.rfind(" ")
        if cut >= 0:
            chunk = self._buf[:cut + 1].strip()
            self._buf = self._buf[cut + 1:]
            self._say(chunk)

    def flush(self):
        rest = self._buf.strip()
        self._buf = ""
        self._say(rest)


def collapse(text):
    """Squeeze blank runs so the history list stays readable."""
    return re.sub(r"\n\s*\n+", "\n", text.strip())
