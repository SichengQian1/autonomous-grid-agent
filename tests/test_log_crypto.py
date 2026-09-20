"""Public RFC 8439 vectors and authenticated log compatibility."""
import base64
import hashlib
import json
import unittest
import zlib
from solution.log_crypto import seal,unseal,chacha_block,poly1305
from solution.telemetry import encode_event,decode_event,_xor_stream,_CODEC_KEY

class CryptoTests(unittest.TestCase):
    def test_rfc8439_block(self):
        block=chacha_block(bytes(range(32)),bytes.fromhex('000000090000004a00000000'),1)
        self.assertEqual(block.hex(),'10f1e7e4d13b5915500fdd1fa32071c4c7d1f4c733c068030422aa9ac3d46c4e'
                         'd2826446079faa0914c2d705d98b02a2b5129cd1de164eb9cbd083e8a2503c4e')

    def test_rfc8439_aead_vector(self):
        key=bytes(range(0x80,0xa0));nonce=bytes.fromhex('070000004041424344454647')
        aad=bytes.fromhex('50515253c0c1c2c3c4c5c6c7')
        plain=bytes.fromhex('4c616469657320616e642047656e746c656d656e206f662074686520636c617373206f66202739393a204966204920636f756c64206f6666657220796f75206f6e6c79206f6e652074697020666f7220746865206675747572652c2073756e73637265656e20776f756c642062652069742e')
        expected=bytes.fromhex('d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d63dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b3692ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc3ff4def08e4b7a9de576d26586cec64b61161ae10b594f09e26a7e902ecbd0600691')
        self.assertEqual(seal(key,nonce,plain,aad),expected)
        self.assertEqual(unseal(key,nonce,expected,aad),plain)
        for field in ('key','nonce','cipher','aad'):
            k,n,c,a=key,nonce,expected,aad
            if field=='key':k=b'x'*32
            if field=='nonce':n=b'x'*12
            if field=='cipher':c=bytes([c[0]^1])+c[1:]
            if field=='aad':a=b'changed'
            with self.assertRaises(ValueError):unseal(k,n,c,a)

    def test_restart_nonces_differ_and_legacy_decodes(self):
        event={'event':'task','text':'synthetic result','r':3}
        first=encode_event(0,event);second=encode_event(0,event)
        self.assertNotEqual(first,second);self.assertEqual(decode_event(first),event)
        nonce=b'\0'*8;cipher=_xor_stream(zlib.compress(json.dumps(event).encode()),nonce)
        tag=hashlib.blake2s(nonce+cipher,key=_CODEC_KEY,digest_size=12).digest()
        self.assertEqual(decode_event('AGLOG2 '+base64.b85encode(nonce+tag+cipher).decode()),event)

    def test_empty_and_block_boundaries(self):
        for n in (0,1,15,16,17,63,64,65,511):
            p=bytes(range(256))*2;p=p[:n]
            self.assertEqual(unseal(b'k'*32,b'n'*12,seal(b'k'*32,b'n'*12,p,b'a'*n),b'a'*n),p)


class DecoderCliTests(unittest.TestCase):
    def test_compressed_new_records_write_utf8_and_refuse_overwrite(self):
        import tempfile,lzma,subprocess,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'match.log.xz');output=Path(root,'decoded.jsonl')
            event={'event':'task','kind':'end','task_id':'T001','outcome':'full','text':'示例'}
            with lzma.open(source,'wt',encoding='utf-8') as stream:stream.write(encode_event(0,event)+'\n')
            command=[sys.executable,'tools/diagnostics/decode_match_log.py',str(source),'--output',str(output)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')),event)
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')),event)

if __name__=='__main__':unittest.main()
