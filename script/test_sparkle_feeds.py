import base64
from pathlib import Path
import sys
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sign_sparkle_feeds import sign_feeds

@unittest.skipUnless(sys.platform=='darwin','Upstream Sparkle signer requires macOS')
class SparkleFeedTests(unittest.TestCase):
    def test_upstream_sign_verify_and_reject_tampering(self):
        seed=bytes(range(32))  # Public fixture; never a production key.
        public=Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        seed_text=base64.b64encode(seed).decode();public_text=base64.b64encode(public).decode()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'appcast-macos-arm64.xml'
            feed.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>Fixture</title></channel></rss>')
            sign_feeds(root,seed_text,public_text)
            sign_feeds(root,seed_text,public_text,True)
            feed.write_text(feed.read_text().replace('Fixture','Tampered'))
            with self.assertRaises(RuntimeError): sign_feeds(root,seed_text,public_text,True)

if __name__=='__main__':unittest.main()
