"""Wireless installer dialog; uses the console's existing ftpd homebrew."""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .ftp_install import FTPSettings, TransferCancelled, test_connection, upload_files


class FTPWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Twin Embers — 无线安装 / FTP")
        self.geometry("760x620")
        self.minsize(700, 580)
        self.transient(parent)
        self._events = queue.Queue()
        self._cancel = threading.Event()
        self._busy = False
        self._closing = False
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="5000")
        self.username = tk.StringVar(value="anonymous")
        self.password = tk.StringVar()
        self.directory = tk.StringVar(value="/3ds/twinembers")
        self.pack = tk.StringVar(value=parent.pack_path.get())
        self.engine = tk.StringVar()
        self.overwrite = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="在 3DS 打开 ftpd，填写屏幕显示的 IP 和端口。")
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="无线安装到 3DS", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(body, text="电脑与 3DS 连接同一局域网；退出游戏后打开 ftpd。\n"
                  "连接信息只用于本次传输，不会保存密码。", wraplength=660).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self._inputs = []
        for row, label, variable, masked in (
            (2, "3DS IP 地址", self.host, False),
            (3, "FTP 端口", self.port, False),
            (4, "用户名", self.username, False),
            (5, "密码", self.password, True),
            (6, "SD 卡目标目录", self.directory, False),
            (7, "数据包 .pak", self.pack, False),
            (8, "游戏程序 .3dsx", self.engine, False),
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            entry = ttk.Entry(body, textvariable=variable, show="*" if masked else "")
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            self._inputs.append(entry)
            if row in (7, 8):
                extension = ".pak" if row == 7 else ".3dsx"
                button = ttk.Button(body, text="选择…", command=lambda v=variable, e=extension: self._pick(v, e))
                button.grid(row=row, column=2, padx=(8, 0))
                self._inputs.append(button)
        replace = ttk.Checkbutton(body, text="更新：替换已有程序／数据包（不修改存档）", variable=self.overwrite)
        replace.grid(row=9, column=0, columnspan=3, sticky="w", pady=10)
        self._inputs.append(replace)
        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=3, sticky="w", pady=8)
        for label, action in (("测试连接", lambda: self._start(True)), ("无线安装", lambda: self._start(False))):
            button = ttk.Button(buttons, text=label, command=action)
            button.pack(side="left", padx=(0, 10))
            self._inputs.append(button)
        self.cancel_button = ttk.Button(buttons, text="取消", command=self._request_cancel, state="disabled")
        self.cancel_button.pack(side="left")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.grid(row=11, column=0, columnspan=3, sticky="ew", pady=10)
        self.progress.grid_remove()
        ttk.Label(body, textvariable=self.status, wraplength=660).grid(
            row=12, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Label(body, text="完成后退出 ftpd，再从 Homebrew Launcher 启动 Twin Embers。\n"
                  "原生双屏版仅接受已适配的数据包；中文 ROM 适配状态见项目说明。",
                  wraplength=660).grid(row=13, column=0, columnspan=3, sticky="w", pady=8)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_after = self.after(100, self._poll)

    def destroy(self):
        self._cancel.set()
        if getattr(self, "_poll_after", None) is not None:
            self.after_cancel(self._poll_after)
            self._poll_after = None
        super().destroy()

    def _pick(self, variable, extension):
        path = filedialog.askopenfilename(parent=self, filetypes=[(extension, "*" + extension)])
        if path:
            variable.set(path)

    def _start(self, check_only):
        if self._busy:
            return
        try:
            settings = FTPSettings(self.host.get().strip(), int(self.port.get()),
                                   self.username.get(), self.password.get(), self.directory.get().strip())
            settings.validate()
            files = {}
            if self.pack.get().strip():
                files["twinembers.pak"] = Path(self.pack.get().strip())
            if self.engine.get().strip():
                files["twinembers.3dsx"] = Path(self.engine.get().strip())
            if not check_only and not files:
                raise ValueError("请选择数据包或游戏程序。")
        except ValueError as exc:
            messagebox.showerror("检查设置", str(exc), parent=self)
            return
        # Read all Tk variables on the UI thread before starting the worker.
        overwrite = self.overwrite.get()
        self._cancel = threading.Event()
        self._busy = True
        for widget in self._inputs:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.grid()
        self.progress.start(12)
        self.status.set("正在连接 3DS…")

        def worker():
            try:
                if check_only:
                    root = test_connection(settings)
                    self._events.put(("ok", "连接成功，FTP 根目录：" + root))
                else:
                    report = upload_files(settings, files, overwrite=overwrite, cancel=self._cancel,
                                          on_progress=lambda step, msg: self._events.put(("progress", msg)))
                    message = "安装完成：" + ", ".join(report["files"]) + "\n退出 ftpd 后即可启动游戏。"
                    if report["warnings"]:
                        message += "\n" + "\n".join(report["warnings"])
                    self._events.put(("ok", message))
            except TransferCancelled as exc:
                self._events.put(("cancelled", str(exc)))
            except Exception as exc:
                self._events.put(("error", str(exc)))
        threading.Thread(target=worker, name="ftp-installer", daemon=False).start()

    def _poll(self):
        self._poll_after = None
        try:
            while True:
                kind, message = self._events.get_nowait()
                self.status.set(message)
                if kind != "progress":
                    self._busy = False
                    self.progress.stop()
                    self.progress.grid_remove()
                    for widget in self._inputs:
                        widget.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if self._closing:
                        self.destroy()
                        return
                    if kind == "error":
                        messagebox.showerror("FTP 安装失败", message, parent=self)
                    elif kind == "ok":
                        messagebox.showinfo("FTP", message, parent=self)
        except queue.Empty:
            pass
        self._poll_after = self.after(100, self._poll)

    def _request_cancel(self):
        self._cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("正在等待当前传输结束并恢复文件，请保持 ftpd 开启…")

    def _close(self):
        if self._busy:
            self._closing = True
            self._request_cancel()
        else:
            self.destroy()
