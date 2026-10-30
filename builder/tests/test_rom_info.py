"""Diagnostics must never relax the native builder's exact-ROM requirement."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from firered3ds_builder.rom import load_rom, ROM_SIZE
from firered3ds_builder.rom_info import inspect_rom


class RomInfoTest(unittest.TestCase):
    def test_bpre_header_alone_does_not_make_a_translation_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gba"
            data = bytearray(ROM_SIZE)
            data[0xac:0xb0] = b"BPRE"
            path.write_bytes(data)
            report = inspect_rom(path)
            self.assertEqual(report["game_code"], "BPRE")
            self.assertEqual(report["profile"], "unknown")
            self.assertFalse(report["native_supported"])
            self.assertNotIn("comparison", report)
            with self.assertRaises(ValueError):
                load_rom(path)
            self.assertEqual(hashlib.sha1(path.read_bytes()).hexdigest(), report["sha1"])

    def test_truncated_rom_is_rejected_before_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gba"
            path.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "16 MiB"):
                inspect_rom(path, compare=True)


if __name__ == "__main__":
    unittest.main()
