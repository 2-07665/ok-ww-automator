"""Console output that also works with Windows redirected legacy encodings."""

from __future__ import annotations

import sys
from typing import TextIO


def console_print(text: str, *, file: TextIO | None = None, flush: bool = False) -> None:
    """Keep diagnostics from failing a task when its output cannot encode them.

    Preserve Unicode on UTF-8 streams and use visible escapes on legacy streams.
    Do not reconfigure process-global streams: runners may be embedded, and the
    caller owns its output encoding. Machine-readable JSON should independently
    use ensure_ascii=True so supplementary characters remain valid JSON escapes.
    """
    stream = sys.stdout if file is None else file
    encoding = getattr(stream, "encoding", None)
    if encoding:
        text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    print(text, file=stream, flush=flush)
