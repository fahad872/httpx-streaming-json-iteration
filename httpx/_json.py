from __future__ import annotations

import json
import typing


class JSONIterator:
    """Frame JSON documents independently of transport chunk boundaries."""

    def __init__(self, content_type: str, **kwargs: typing.Any) -> None:
        media_type = content_type.partition(";")[0].strip().lower()
        if media_type in ("application/x-ndjson", "application/ndjson"):
            self.separator = "\n"
        elif media_type == "application/json-seq":
            self.separator = "\x1e"
        elif media_type == "application/json" or (
            media_type.startswith("application/") and media_type.endswith("+json")
        ):
            self.separator = ""
        else:
            raise ValueError(f"Unsupported JSON Content-Type: {content_type!r}")
        self.kwargs = kwargs
        self.buffer = ""
        self.started = False

    def decode(self, text: str) -> typing.Iterator[typing.Any]:
        self.buffer += text
        if not self.separator:
            return
        while self.separator in self.buffer:
            record, self.buffer = self.buffer.split(self.separator, 1)
            if self.separator == "\x1e" and not self.started:
                if record.strip():
                    raise json.JSONDecodeError("Expected record separator", record, 0)
                self.started = True
                continue
            if record.strip():
                yield json.loads(record, **self.kwargs)

    def flush(self) -> typing.Iterator[typing.Any]:
        record, self.buffer = self.buffer, ""
        if self.separator == "\x1e" and not self.started and record.strip():
            raise json.JSONDecodeError("Expected record separator", record, 0)
        if not self.separator or record.strip():
            yield json.loads(record, **self.kwargs)
