"""FTP transaction checks with synthetic files and injected server failures."""
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from ftplib import error_perm

from firered3ds_builder import ftp_install as install
from firered3ds_builder.pak import PakError, write_pak


class Server:
    def __init__(self):
        self.files = {"twinembers.sav": b"USER SAVE", "twinembers.sav.bak": b"BACKUP SAVE"}
        self.corrupt = False
        self.fail_rename = None
        self.lose_reply = False
        self.connects = 0

    def factory(self):
        server = self

        class Connection:
            def connect(self, *args, **kwargs):
                server.connects += 1

            def login(self, *args): pass
            def set_pasv(self, value): pass
            def close(self): pass
            def cwd(self, value): pass
            def pwd(self): return "/"
            def nlst(self): return list(server.files)

            def storbinary(self, command, source, blocksize):
                server.files[command[5:]] = source.read()

            def retrbinary(self, command, callback, blocksize):
                data = server.files[command[5:]]
                callback(data + b"CORRUPT" if server.corrupt else data)

            def rename(self, old, new):
                if new == server.fail_rename:
                    server.fail_rename = None
                    raise error_perm("550 injected rename failure")
                server.files[new] = server.files.pop(old)
                if new.endswith(".3dsx") and server.lose_reply:
                    server.lose_reply = False
                    raise EOFError("reply lost after the rename completed")

            def delete(self, name):
                del server.files[name]

        return Connection()


class FTPInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root / "twinembers.3dsx"
        self.game.write_bytes(b"3DSX" + bytes(28) + b"SYNTHETIC EXECUTABLE")
        self.pack = self.root / "twinembers.pak"
        self.pack.write_bytes(b"SYNTHETIC PACK")
        self.server = Server()
        self.settings = install.FTPSettings("127.0.0.1")

    def upload(self, files=None, **kwargs):
        return install.upload_files(self.settings, files or {"twinembers.3dsx": self.game},
                                    ftp_factory=self.server.factory, **kwargs)

    def test_fresh_install_reads_back_and_preserves_saves(self):
        report = self.upload()
        self.assertEqual(self.server.files, {"twinembers.sav": b"USER SAVE",
                         "twinembers.sav.bak": b"BACKUP SAVE", "twinembers.3dsx": self.game.read_bytes()})
        self.assertEqual(report["sha256"]["twinembers.3dsx"], hashlib.sha256(self.game.read_bytes()).hexdigest())

    def test_existing_file_requires_explicit_overwrite(self):
        self.server.files["twinembers.3dsx"] = b"OLD GAME"
        before = dict(self.server.files)
        with self.assertRaises(FileExistsError):
            self.upload()
        self.assertEqual(self.server.files, before)

    def test_corrupt_transfer_never_publishes(self):
        self.server.files["twinembers.3dsx"] = b"OLD GAME"
        before = dict(self.server.files)
        self.server.corrupt = True
        with self.assertRaisesRegex(OSError, "verification failed"):
            self.upload(overwrite=True)
        self.assertEqual(self.server.files, before)

    def test_rename_failure_restores_both_old_files(self):
        self.server.files.update({"twinembers.3dsx": b"OLD GAME", "twinembers.pak": b"OLD PACK"})
        before = dict(self.server.files)
        self.server.fail_rename = "twinembers.3dsx"
        with patch.object(install, "validate_files", return_value={"twinembers.pak": self.pack,
                                                                  "twinembers.3dsx": self.game}):
            with self.assertRaises(error_perm):
                self.upload(overwrite=True)
        self.assertEqual(self.server.files, before)

    def test_lost_rename_reply_recovers_using_server_state(self):
        self.server.files["twinembers.3dsx"] = b"OLD GAME"
        before = dict(self.server.files)
        self.server.lose_reply = True
        with self.assertRaises(EOFError):
            self.upload(overwrite=True)
        self.assertEqual(self.server.files, before)
        self.assertEqual(self.server.connects, 2)

    def test_new_file_with_lost_reply_is_removed_on_rollback(self):
        before = dict(self.server.files)
        self.server.lose_reply = True
        with self.assertRaises(EOFError):
            self.upload()
        self.assertEqual(self.server.files, before)

    def test_cancel_after_staging_preserves_old_game(self):
        self.server.files["twinembers.3dsx"] = b"OLD GAME"
        before = dict(self.server.files)
        cancel = threading.Event()
        def progress(step, message):
            if step == "verify":
                cancel.set()
        with self.assertRaises(install.TransferCancelled):
            self.upload(overwrite=True, cancel=cancel, on_progress=progress)
        self.assertEqual(self.server.files, before)

    def test_invalid_files_never_connect(self):
        for name, path in (("twinembers.sav", self.game), ("twinembers.pak", self.pack)):
            with self.subTest(name=name), self.assertRaises((ValueError, PakError)):
                self.upload(files={name: path})
        self.game.write_bytes(b"not an executable")
        with self.assertRaises(ValueError):
            self.upload()
        self.assertEqual(self.server.connects, 0)

    def test_valid_header_with_missing_game_data_is_rejected(self):
        recipe = install.load_recipe(install.default_recipe(install.SUPPORTED_SHA1))
        write_pak(self.pack, [("test/fixture.bin", b"fixture")], recipe["engine_abi"],
                  bytes.fromhex(install.SUPPORTED_SHA1))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.upload(files={"twinembers.pak": self.pack})
        self.assertEqual(self.server.connects, 0)

    def test_settings_reject_command_injection_and_traversal(self):
        for settings in (install.FTPSettings("ftp://127.0.0.1"),
                         install.FTPSettings("127.0.0.1\r\nDELE save"),
                         install.FTPSettings("127.0.0.1", port=0),
                         install.FTPSettings("127.0.0.1", directory="/3ds/../saves"),
                         install.FTPSettings("127.0.0.1", password="secret\r\nDELE save")):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.validate()
        self.assertNotIn("secret", repr(install.FTPSettings("localhost", password="secret")))


if __name__ == "__main__":
    unittest.main()
