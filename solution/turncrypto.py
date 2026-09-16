"""Standard-library-only authenticated encryption for turn logs.

ChaCha20 (RFC 8439) stream cipher plus HMAC-SHA256 encrypt-then-MAC.
Keys are derived from a passphrase with scrypt, falling back to PBKDF2
when the interpreter's OpenSSL lacks scrypt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from typing import Any


ALGORITHM = "chacha20-hmac-sha256"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
PBKDF2_ROUNDS = 200_000
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 32
_MASK = 0xFFFFFFFF


def _rotl32(value: int, shift: int) -> int:
    return ((value << shift) & _MASK) | (value >> (32 - shift))


def _quarter_round(state: list[int], a: int, b: int, c: int, d: int) -> None:
    state[a] = (state[a] + state[b]) & _MASK
    state[d] = _rotl32(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & _MASK
    state[b] = _rotl32(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & _MASK
    state[d] = _rotl32(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & _MASK
    state[b] = _rotl32(state[b] ^ state[c], 7)


def _block(key: bytes, counter: int, nonce: bytes) -> bytes:
    constants = struct.unpack("<4I", b"expand 32-byte k")
    state = list(constants) + list(struct.unpack("<8I", key))
    state += [counter & _MASK] + list(struct.unpack("<3I", nonce))
    working = state.copy()
    for _ in range(10):
        _quarter_round(working, 0, 4, 8, 12)
        _quarter_round(working, 1, 5, 9, 13)
        _quarter_round(working, 2, 6, 10, 14)
        _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15)
        _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7, 8, 13)
        _quarter_round(working, 3, 4, 9, 14)
    return struct.pack("<16I", *[(x + y) & _MASK for x, y in zip(working, state)])


def chacha20_xor(key: bytes, nonce: bytes, data: bytes, counter: int = 1) -> bytes:
    if len(key) != 32 or len(nonce) != NONCE_BYTES:
        raise ValueError("chacha20 requires a 32-byte key and 12-byte nonce")
    output = bytearray(len(data))
    for offset in range(0, len(data), 64):
        block = _block(key, counter, nonce)
        chunk = data[offset:offset + 64]
        output[offset:offset + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, block))
        counter = (counter + 1) & _MASK
    return bytes(output)


def _derive(password: bytes, salt: bytes, info: dict[str, Any]) -> tuple[bytes, bytes]:
    name = info.get("kdf")
    if name == "scrypt" and hasattr(hashlib, "scrypt"):
        material = hashlib.scrypt(
            password, salt=salt,
            n=int(info.get("n", SCRYPT_N)),
            r=int(info.get("r", SCRYPT_R)),
            p=int(info.get("p", SCRYPT_P)),
            dklen=64,
        )
    elif name == "pbkdf2-hmac-sha256":
        material = hashlib.pbkdf2_hmac(
            "sha256", password, salt, int(info.get("rounds", PBKDF2_ROUNDS)), dklen=64,
        )
    else:
        raise ValueError("unsupported key derivation")
    return material[:32], material[32:]


def derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes, dict[str, Any]]:
    password = passphrase.encode("utf-8")
    info: dict[str, Any] = {"kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P}
    try:
        return (*_derive(password, salt, info), info)
    except ValueError:
        info = {"kdf": "pbkdf2-hmac-sha256", "rounds": PBKDF2_ROUNDS}
        return (*_derive(password, salt, info), info)


def _b64decode(raw: object, length: int) -> bytes:
    if not isinstance(raw, str):
        raise ValueError("encrypted record field must be a string")
    data = base64.b64decode(raw.encode("ascii"), validate=True)
    if len(data) != length:
        raise ValueError("encrypted record field has an invalid length")
    return data


class TurnLogCipher:
    """Per-file cipher: fresh salt, per-record random nonce and sequence tag."""

    def __init__(self, enc_key: bytes, mac_key: bytes, kdf: dict[str, Any], salt: bytes) -> None:
        self._enc_key = enc_key
        self._mac_key = mac_key
        self._kdf = kdf
        self._salt = salt

    @classmethod
    def from_passphrase(cls, passphrase: str, salt: bytes | None = None) -> TurnLogCipher:
        salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
        enc_key, mac_key, kdf = derive_keys(passphrase, salt)
        return cls(enc_key, mac_key, kdf, salt)

    @classmethod
    def from_header(cls, passphrase: str, header: dict[str, Any]) -> TurnLogCipher:
        info = header.get("turnlog") if isinstance(header, dict) else None
        if not isinstance(info, dict) or info.get("enc") != ALGORITHM:
            raise ValueError("not an encrypted turn log header")
        salt = _b64decode(info.get("salt"), SALT_BYTES)
        enc_key, mac_key = _derive(passphrase.encode("utf-8"), salt, info)
        return cls(enc_key, mac_key, dict(info), salt)

    def header(self) -> dict[str, Any]:
        return {
            "turnlog": {
                "v": 1,
                "enc": ALGORITHM,
                "salt": base64.b64encode(self._salt).decode("ascii"),
                **self._kdf,
            }
        }

    def encrypt(self, seq: int, plaintext: bytes) -> dict[str, Any]:
        nonce = secrets.token_bytes(NONCE_BYTES)
        ciphertext = chacha20_xor(self._enc_key, nonce, plaintext)
        tag = hmac.new(
            self._mac_key,
            seq.to_bytes(8, "big") + nonce + ciphertext,
            hashlib.sha256,
        ).digest()
        return {
            "v": 1,
            "seq": seq,
            "n": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ciphertext).decode("ascii"),
            "tag": base64.b64encode(tag).decode("ascii"),
        }

    def decrypt(self, record: dict[str, Any]) -> bytes:
        seq = int(record.get("seq", -1))
        if not 0 <= seq < 1 << 63:
            raise ValueError("encrypted record sequence is invalid")
        nonce = _b64decode(record.get("n"), NONCE_BYTES)
        tag = _b64decode(record.get("tag"), TAG_BYTES)
        raw_ct = record.get("ct")
        if not isinstance(raw_ct, str):
            raise ValueError("encrypted record field must be a string")
        ciphertext = base64.b64decode(raw_ct.encode("ascii"), validate=True)
        expected = hmac.new(
            self._mac_key,
            seq.to_bytes(8, "big") + nonce + ciphertext,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, tag):
            raise ValueError("encrypted record authentication failed")
        return chacha20_xor(self._enc_key, nonce, ciphertext)
