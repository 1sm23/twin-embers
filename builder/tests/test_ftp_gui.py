"""Exercise the real wireless dialog without making a network connection."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "Native Tk dialog smoke test runs on Windows")
class FTPGuiTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from firered3ds_builder.ftp_gui import FTPWindow
        self.parent = tk.Tk()
        self.parent.geometry("300x200+10000+10000")
        self.parent.pack_path = tk.StringVar(value="")
        self.window = FTPWindow(self.parent)
        self.window.geometry("760x620+10000+10000")
        self.parent.update()

    def tearDown(self):
        self.parent.destroy()

    def test_connect_uses_form_and_returns_to_idle(self):
        self.window.host.set("127.0.0.1")
        self.window.password.set("private-password")
        def thread(*, target, **kwargs):
            return SimpleNamespace(start=target)
        with patch("firered3ds_builder.ftp_gui.threading.Thread", side_effect=thread), \
             patch("firered3ds_builder.ftp_gui.test_connection", return_value="/") as connect, \
             patch("firered3ds_builder.ftp_gui.messagebox.showinfo"):
            self.window._start(True)
            self.assertTrue(self.window._busy)
            settings = connect.call_args.args[0]
            self.assertEqual(settings.host, "127.0.0.1")
            self.assertEqual(settings.password, "private-password")
            self.assertNotIn("private-password", repr(settings))
            self.window.after_cancel(self.window._poll_after)
            self.window._poll()
            self.assertFalse(self.window._busy)
            self.assertIn("连接成功", self.window.status.get())

    def test_invalid_address_and_missing_files_do_not_start_a_worker(self):
        with patch("firered3ds_builder.ftp_gui.threading.Thread") as worker, \
             patch("firered3ds_builder.ftp_gui.messagebox.showerror"):
            self.window._start(True)
            self.window.host.set("127.0.0.1")
            self.window._start(False)
            worker.assert_not_called()

    def test_controls_fit_minimum_window(self):
        self.window.geometry("700x580+10000+10000")
        self.parent.update()
        bottom = self.window.winfo_rooty() + self.window.winfo_height()
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)
        for widget in descendants(self.window):
            if not widget.winfo_ismapped():
                continue
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.window.winfo_rootx() + self.window.winfo_width())


if __name__ == "__main__":
    unittest.main()
