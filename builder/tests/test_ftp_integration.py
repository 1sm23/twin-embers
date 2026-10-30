"""Real FTP wire-protocol test against an isolated localhost server, no game data."""
import importlib.util
import logging
from pathlib import Path
import tempfile
import threading
import unittest

from firered3ds_builder.ftp_install import FTPSettings, test_connection, upload_files


@unittest.skipUnless(importlib.util.find_spec("pyftpdlib"), "optional FTP integration dependency: pyftpdlib")
class FTPIntegrationTest(unittest.TestCase):
    def test_passive_transfer_readback_replace_and_save_preservation(self):
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
        from pyftpdlib.log import config_logging
        config_logging(level=logging.ERROR)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            card = root / "sd"
            card.mkdir()
            authorizer = DummyAuthorizer()
            authorizer.add_user("test", "test-password", str(card), perm="elradfmwMT")
            class Handler(FTPHandler):
                pass
            Handler.authorizer = authorizer
            server = FTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=lambda: server.serve_forever(timeout=0.1,
                                        blocking=True, handle_exit=False), daemon=True)
            thread.start()
            try:
                settings = FTPSettings("127.0.0.1", server.socket.getsockname()[1], "test", "test-password")
                self.assertEqual(test_connection(settings), "/")
                game = root / "source.3dsx"
                game.write_bytes(b"3DSX" + bytes(28) + b"synthetic" * 100000)
                report = upload_files(settings, {"twinembers.3dsx": game})
                destination = card / "3ds" / "twinembers"
                self.assertEqual((destination / "twinembers.3dsx").read_bytes(), game.read_bytes())
                save = destination / "twinembers.sav"
                save.write_bytes(b"USER SAVE FIXTURE")
                game.write_bytes(b"3DSX" + bytes(28) + b"updated synthetic executable")
                with self.assertRaises(FileExistsError):
                    upload_files(settings, {"twinembers.3dsx": game})
                upload_files(settings, {"twinembers.3dsx": game}, overwrite=True)
                self.assertEqual((destination / "twinembers.3dsx").read_bytes(), game.read_bytes())
                self.assertEqual(save.read_bytes(), b"USER SAVE FIXTURE")
                self.assertEqual(sorted(p.name for p in destination.iterdir()),
                                 ["twinembers.3dsx", "twinembers.sav"])
                self.assertEqual(report["files"], ["twinembers.3dsx"])
            finally:
                server.close_all()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
