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
        self.mode = "start"
        self.position = 0
        self.depth = 0
        self.in_string = False
        self.escaped = False
        self.allow_empty = True

    def decode(self, text: str) -> typing.Iterator[typing.Any]:
        self.buffer += text
        if not self.separator:
            yield from self._decode_document()
            return
        while self.separator in self.buffer:
            record, self.buffer = self.buffer.split(self.separator, 1)
            if self.separator == "\x1e" and not self.started:
                if record:
                    raise json.JSONDecodeError("Expected record separator", record, 0)
                self.started = True
                continue
            if record.strip():
                yield json.loads(record, **self.kwargs)

    def _decode_document(self) -> typing.Iterator[typing.Any]:
        if self.mode == "start":
            self.buffer = self.buffer.lstrip(" \t\r\n")
            if not self.buffer:
                return
            self.mode = "array" if self.buffer.startswith("[") else "document"
            if self.mode == "array":
                self.buffer = self.buffer[1:]
        if self.mode == "document":
            return
        if self.mode == "done":
            if self.buffer.strip(" \t\r\n"):
                raise json.JSONDecodeError("Extra data", self.buffer, 0)
            self.buffer = ""
            return

        while self.position < len(self.buffer):
            char = self.buffer[self.position]
            if self.in_string:
                if self.escaped:
                    self.escaped = False
                elif char == "\\":
                    self.escaped = True
                elif char == '"':
                    self.in_string = False
            elif char == '"':
                self.in_string = True
            elif self.depth == 0 and char in ",]":
                record = self.buffer[: self.position]
                if record.strip(" \t\r\n"):
                    value = json.loads(record, **self.kwargs)
                elif char == "," or not self.allow_empty:
                    raise json.JSONDecodeError("Expected array item", self.buffer, 0)
                else:
                    self.buffer = self.buffer[self.position + 1 :]
                    self.mode = "done"
                    yield from self._decode_document()
                    return
                self.buffer = self.buffer[self.position + 1 :]
                self.position = 0
                self.allow_empty = False
                if char == "]":
                    self.mode = "done"
                yield value
                if self.mode == "done":
                    yield from self._decode_document()
                    return
                continue
            elif char in "[{":
                self.depth += 1
            elif char in "]}":
                self.depth -= 1
            self.position += 1

    def flush(self) -> typing.Iterator[typing.Any]:
        if not self.separator:
            yield from self._decode_document()
            if self.mode == "done":
                return
            if self.mode == "array":
                raise json.JSONDecodeError(
                    "Unterminated array", self.buffer, len(self.buffer)
                )
            record, self.buffer = self.buffer, ""
            yield json.loads(record, **self.kwargs)
            return
        record, self.buffer = self.buffer, ""
        if self.separator == "\x1e":
            if not self.started:
                if record:
                    raise json.JSONDecodeError("Expected record separator", record, 0)
                return
            # An RS starts a record even when no JSON follows it before EOF.
            yield json.loads(record, **self.kwargs)
        elif record.strip():
            yield json.loads(record, **self.kwargs)
