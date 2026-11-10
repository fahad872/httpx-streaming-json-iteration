import gzip
import json
import typing
from decimal import Decimal

import pytest

import httpx


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content_type, body, expected",
    [
        ("application/json", '[1, {"name": "café"}]', [1, {"name": "café"}]),
        ("application/json", " [] \r\n", []),
        ("application/vnd.test+json", "[[], [1, 2], {}, null]", [[], [1, 2], {}, None]),
        (
            "application/json",
            "[1.25e+2, -123, true, false]",
            [125.0, -123, True, False],
        ),
        (
            "application/json",
            '["a,b]", "escaped\\"", "slash\\\\"]',
            ["a,b]", 'escaped"', "slash\\"],
        ),
        ("application/json", "123", [123]),
        ("application/x-ndjson", "\r\n \t\n[1, 2]\n\n{}\n", [[1, 2], {}]),
        ("Application/Problem+JSON; charset=utf-8", '{"a": 1}', [{"a": 1}]),
        ("application/x-ndjson", '\n{"a": 1}\r\nnull\n42', [{"a": 1}, None, 42]),
        ("application/ndjson", '"café"\nfalse\n', ["café", False]),
        ("application/json-seq", '\x1e{\n"a": 1\n}\n\x1e42\n', [{"a": 1}, 42]),
        ("application/json-seq", "\x1e\x1enull\n", [None]),
        ("application/x-ndjson", "", []),
        ("application/json-seq", "", []),
    ],
)
async def test_json_formats(content_type, body, expected):
    # Every byte is a separate chunk, including multi-byte UTF-8 characters.
    chunks = [bytes([byte]) for byte in body.encode()]

    async def async_body() -> typing.AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    response = httpx.Response(
        200, headers={"content-type": content_type}, content=iter(chunks)
    )
    assert list(response.iter_json()) == expected
    assert response.is_closed
    response = httpx.Response(
        200, headers={"content-type": content_type}, content=async_body()
    )
    assert [value async for value in response.aiter_json()] == expected
    assert response.is_closed


@pytest.mark.anyio
@pytest.mark.parametrize("encoding", ["utf-16", "iso-8859-1"])
@pytest.mark.parametrize(
    "media_type, document",
    [
        ("application/x-ndjson", '"café"\n1.25\n'),
        ("application/json", '["café", 1.25]'),
    ],
)
async def test_json_encoding_and_compression(encoding, media_type, document):
    body = gzip.compress(document.encode(encoding))
    headers = {
        "content-type": f"{media_type}; charset={encoding}",
        "content-encoding": "gzip",
    }
    chunks = [body[index : index + 1] for index in range(len(body))]

    async def async_body() -> typing.AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    response = httpx.Response(200, headers=headers, content=iter(chunks))
    assert list(response.iter_json(parse_float=Decimal)) == ["café", Decimal("1.25")]
    response = httpx.Response(200, headers=headers, content=async_body())
    assert [value async for value in response.aiter_json(parse_float=Decimal)] == [
        "café",
        Decimal("1.25"),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content_type, body",
    [
        ("application/json", b""),
        ("application/json", b"{} trailing"),
        *[
            ("application/json", body)
            for body in [
                b"[",
                b"[1",
                b"[1,]",
                b"[,1]",
                b"[1,,2]",
                b"[1 2]",
                b"[] trailing",
                b"[{}",
                b'["unterminated]',
                b"[1e,2]",
            ]
        ],
        ("application/x-ndjson", b"{}\n{broken}\n"),
        ("application/json-seq", b"{}\x1e{}"),
        ("application/json-seq", b"\x1e{broken}"),
    ],
)
async def test_json_invalid(content_type, body):
    response = httpx.Response(200, headers={"content-type": content_type}, content=body)
    with pytest.raises(json.JSONDecodeError):
        list(response.iter_json())
    with pytest.raises(json.JSONDecodeError):
        [value async for value in response.aiter_json()]


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", ["", "text/plain", "text/custom+json"])
async def test_json_unsupported_type(content_type):
    response = httpx.Response(
        200, headers={"content-type": content_type}, content=b"{}"
    )
    with pytest.raises(ValueError, match="Unsupported JSON Content-Type"):
        list(response.iter_json())
    with pytest.raises(ValueError, match="Unsupported JSON Content-Type"):
        [value async for value in response.aiter_json()]


@pytest.mark.parametrize(
    "content_type, first, rest",
    [
        ("application/x-ndjson", b'{"a": 1}\n', b"null\n"),
        ("application/json", b'[{"a": 1},', b"null]"),
    ],
)
def test_json_yields_before_end_of_stream(content_type, first, rest):
    received = False

    def body() -> typing.Iterator[bytes]:
        yield first
        assert received, "The first record must arrive before reading further"
        yield rest

    response = httpx.Response(
        200, headers={"content-type": content_type}, content=body()
    )
    iterator = response.iter_json()
    assert next(iterator) == {"a": 1}
    received = True
    assert list(iterator) == [None]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content_type, first, rest",
    [
        ("application/x-ndjson", b'{"a": 1}\n', b"null\n"),
        ("application/json", b'[{"a": 1},', b"null]"),
    ],
)
async def test_json_yields_before_end_of_async_stream(content_type, first, rest):
    received = False

    async def body() -> typing.AsyncIterator[bytes]:
        yield first
        assert received, "The first record must arrive before reading further"
        yield rest

    response = httpx.Response(
        200, headers={"content-type": content_type}, content=body()
    )
    iterator = response.aiter_json()
    assert await iterator.__anext__() == {"a": 1}
    received = True
    assert [value async for value in iterator] == [None]
