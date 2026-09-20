"""Bounded RFC 8439 ChaCha20-Poly1305 for dependency-free log transport.

This pure-Python implementation is not constant-time. It is restricted to local
telemetry; it is not a general network cryptography service. Publicly distributed
keys provide no secrecy against readers of the distribution.
"""
import hmac
import struct

MAX_MESSAGE = 256 * 1024


def chacha_block(key: bytes, nonce: bytes, counter: int) -> bytes:
    if len(key) != 32 or len(nonce) != 12 or not 0 <= counter < 2**32:
        raise ValueError('invalid ChaCha20 parameters')
    state = list(struct.unpack('<4I', b'expand 32-byte k')) + list(struct.unpack('<8I',key))
    state += [counter] + list(struct.unpack('<3I',nonce))
    words = state.copy()
    def rotate(value, bits): return ((value << bits) & 0xffffffff) | (value >> (32-bits))
    def quarter(a,b,c,d):
        words[a]=(words[a]+words[b]) & 0xffffffff; words[d]=rotate(words[d]^words[a],16)
        words[c]=(words[c]+words[d]) & 0xffffffff; words[b]=rotate(words[b]^words[c],12)
        words[a]=(words[a]+words[b]) & 0xffffffff; words[d]=rotate(words[d]^words[a],8)
        words[c]=(words[c]+words[d]) & 0xffffffff; words[b]=rotate(words[b]^words[c],7)
    for _ in range(10):
        quarter(0,4,8,12);quarter(1,5,9,13);quarter(2,6,10,14);quarter(3,7,11,15)
        quarter(0,5,10,15);quarter(1,6,11,12);quarter(2,7,8,13);quarter(3,4,9,14)
    return struct.pack('<16I',*((a+b)&0xffffffff for a,b in zip(state,words)))


def _stream(key,nonce,message):
    if len(message)>MAX_MESSAGE:raise ValueError('log message too large')
    result=bytearray()
    for offset in range(0,len(message),64):
        block=chacha_block(key,nonce,1+offset//64)
        result.extend(a^b for a,b in zip(message[offset:offset+64],block))
    return bytes(result)


def poly1305(key: bytes, message: bytes) -> bytes:
    if len(key)!=32:raise ValueError('invalid Poly1305 key')
    r=int.from_bytes(key[:16],'little') & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s=int.from_bytes(key[16:],'little');acc=0
    for offset in range(0,len(message),16):
        n=int.from_bytes(message[offset:offset+16]+b'\x01','little')
        acc=((acc+n)*r) % (2**130-5)
    return ((acc+s) % 2**128).to_bytes(16,'little')


def _tag(key,nonce,cipher,aad):
    if len(cipher)>MAX_MESSAGE or len(aad)>1024:raise ValueError('log message too large')
    mac=aad+b'\0'*(-len(aad)%16)+cipher+b'\0'*(-len(cipher)%16)+struct.pack('<QQ',len(aad),len(cipher))
    return poly1305(chacha_block(key,nonce,0)[:32],mac)


def seal(key: bytes, nonce: bytes, plain: bytes, aad: bytes=b'') -> bytes:
    cipher=_stream(key,nonce,plain)
    return cipher+_tag(key,nonce,cipher,aad)


def unseal(key: bytes, nonce: bytes, sealed: bytes, aad: bytes=b'') -> bytes:
    if len(sealed)<16:raise ValueError('truncated authentication tag')
    cipher,tag=sealed[:-16],sealed[-16:]
    if not hmac.compare_digest(tag,_tag(key,nonce,cipher,aad)):
        raise ValueError('log authentication failed (wrong key or damaged record)')
    return _stream(key,nonce,cipher)
