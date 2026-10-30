"""Install local game files on a 3DS running ftpd, without removing its SD card.

Stage and read back every file before publishing. Save files are never targets.
The standard FTP protocol is intended for a trusted local network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from ftplib import FTP, all_errors
import hashlib
from pathlib import Path, PurePosixPath
import uuid
from typing import Callable

from .build import default_recipe
from .pak import PakReader, path_id
from .recipe import load_recipe
from .rom import SUPPORTED_SHA1

ALLOWED_FILES = frozenset(("twinembers.pak", "twinembers.3dsx"))
Progress = Callable[[str, str], None]


class TransferCancelled(Exception):
    """Cancellation takes effect between complete FTP commands."""


@dataclass(frozen=True)
class FTPSettings:
    host: str
    port: int = 5000
    username: str = "anonymous"
    password: str = field(default="", repr=False)
    directory: str = "/3ds/twinembers"
    timeout: float = 20

    def validate(self) -> None:
        if (not self.host or self.host != self.host.strip()
                or any(c.isspace() or c in "/\\\x00" for c in self.host)
                or "://" in self.host):
            raise ValueError("Enter only the 3DS IP address or hostname, without ftp:// or a path.")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("FTP port must be between 1 and 65535 (ftpd usually uses 5000).")
        for value in (self.username, self.password, self.directory):
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("FTP settings must not contain control characters.")
        parts = self.directory.split("/")
        if (not self.directory.startswith("/") or "\\" in self.directory
                or any(p in (".", "..") for p in parts)
                or str(PurePosixPath(self.directory)) == "/"):
            raise ValueError("Choose an absolute FTP folder, for example /3ds/twinembers.")
        if self.timeout <= 0:
            raise ValueError("FTP timeout must be positive.")


def _notify(callback: Progress | None, step: str, message: str) -> None:
    if callback:
        callback(step, message)


def _cancel(event) -> None:
    if event is not None and event.is_set():
        raise TransferCancelled("Transfer cancelled. Previously installed files were preserved.")


def _connect(settings: FTPSettings, factory):
    ftp = factory()
    try:
        ftp.connect(settings.host, settings.port, timeout=settings.timeout)
        ftp.login(settings.username or "anonymous", settings.password)
        ftp.set_pasv(True)
        return ftp
    except BaseException:
        ftp.close()
        raise


def _enter_directory(ftp, directory: str, *, create: bool) -> None:
    ftp.cwd("/")
    for component in PurePosixPath(directory).parts[1:]:
        try:
            ftp.cwd(component)
        except all_errors:
            if not create:
                raise
            # Do not suppress a denied MKD or a broken connection.
            ftp.mkd(component)
            ftp.cwd(component)


def _names(ftp) -> set[str]:
    return {PurePosixPath(n.rstrip("/")).name for n in ftp.nlst()}


def _remote_digest(ftp, name: str) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()

    def consume(block: bytes) -> None:
        nonlocal size
        size += len(block)
        digest.update(block)

    ftp.retrbinary("RETR " + name, consume, blocksize=64 * 1024)
    return size, digest.hexdigest()


def validate_files(files: dict[str, str | Path]) -> dict[str, Path]:
    """Validate content before opening the network connection."""
    if not files or set(files) - ALLOWED_FILES:
        raise ValueError("Select twinembers.pak and/or twinembers.3dsx. Saves cannot be uploaded here.")
    result = {name: Path(path).expanduser().resolve() for name, path in files.items()}
    for name, path in result.items():
        if not path.is_file():
            raise ValueError(f"Local file not found: {path}")
        if name.endswith(".pak"):
            recipe = load_recipe(default_recipe(SUPPORTED_SHA1))
            with PakReader(path, recipe["engine_abi"], bytes.fromhex(SUPPORTED_SHA1)) as reader:
                for entry in recipe["entries"]:
                    actual = reader.entries.get(path_id(entry["path"]))
                    if actual is None or (actual.raw_size, actual.crc32) != (entry["size"], entry["crc32"]):
                        raise ValueError("Pack is incomplete or does not match this engine: " + entry["path"])
                reader.verify()
        else:
            with path.open("rb") as source:
                header = source.read(32)
            if len(header) != 32 or header[:4] != b"3DSX":
                raise ValueError("The selected game executable is not a 3DSX file.")
    return result


def test_connection(settings: FTPSettings, *, ftp_factory=FTP) -> str:
    settings.validate()
    ftp = _connect(settings, ftp_factory)
    try:
        ftp.cwd("/")
        return ftp.pwd()
    finally:
        ftp.close()


def upload_files(settings: FTPSettings, files: dict[str, str | Path], *,
                 overwrite: bool = False, on_progress: Progress | None = None,
                 cancel=None, ftp_factory=FTP) -> dict:
    """Stage all files, verify by downloading, then publish with rollback backups.

    Run ftpd with Twin Embers closed. FTP cannot rename two files atomically;
    this routine restores both previous files if publication fails. If the
    network also prevents recovery it reports the retained backup names.
    """
    settings.validate()
    paths = validate_files(files)
    expected = {name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
                for name, path in paths.items()}
    _cancel(cancel)
    _notify(on_progress, "connect", "Connecting to the 3DS ftpd server...")
    ftp = _connect(settings, ftp_factory)
    token = uuid.uuid4().hex
    staged = {n: f".te-{token}-{n}.upload" for n in paths}
    backups = {n: f".te-{token}-{n}.previous" for n in paths}
    originals: set[str] = set()
    staging_started = False
    publishing = False
    warnings: list[str] = []
    try:
        _enter_directory(ftp, settings.directory, create=True)
        originals = _names(ftp) & set(paths)
        if originals and not overwrite:
            raise FileExistsError("Files already installed: " + ", ".join(sorted(originals))
                                  + ". Enable replacement to update them.")
        for name, path in paths.items():
            _cancel(cancel)
            _notify(on_progress, "upload", f"Uploading {name} ({expected[name][0]:,} bytes)...")
            with path.open("rb") as source:
                staging_started = True
                ftp.storbinary("STOR " + staged[name], source, blocksize=64 * 1024)
            _notify(on_progress, "verify", f"Reading back {name} to verify SHA-256...")
            if _remote_digest(ftp, staged[name]) != expected[name]:
                raise OSError(f"FTP read-back verification failed for {name}; previous files preserved.")
        _cancel(cancel)
        # Recheck just before publication so a file created during staging is
        # never overwritten when overwrite=False.
        if not overwrite and (_names(ftp) & set(paths)):
            raise FileExistsError("A destination file appeared during transfer; refusing replacement.")
        _notify(on_progress, "publish", "Installing the verified files on the 3DS...")
        publishing = True
        for name in paths:
            if name in originals:
                ftp.rename(name, backups[name])
            ftp.rename(staged[name], name)
        # From here the installation is complete; backup deletion failure
        # must not turn a successful transaction into a partial rollback.
        publishing = False
        for name in originals:
            try:
                ftp.delete(backups[name])
            except all_errors:
                warnings.append(f"Previous file retained at {settings.directory}/{backups[name]}")
        _notify(on_progress, "done", "FTP installation complete. Close ftpd and launch Twin Embers.")
        return {"directory": settings.directory, "files": list(paths),
                "sha256": {n: expected[n][1] for n in paths}, "warnings": warnings}
    except BaseException as error:
        # Reconnect before recovery: a timeout can occur after a server has
        # already performed a rename but before the client receives its reply.
        ftp.close()
        if not staging_started:
            raise
        recovery = None
        try:
            recovery = _connect(settings, ftp_factory)
            _enter_directory(recovery, settings.directory, create=False)
            names = _names(recovery)
            if publishing:
                for name in reversed(list(paths)):
                    if backups[name] in names:
                        if name in names:
                            recovery.delete(name)
                        recovery.rename(backups[name], name)
                    elif name not in originals and staged[name] not in names and name in names:
                        # A new file was published, possibly with a lost reply.
                        recovery.delete(name)
            for temporary in staged.values():
                if temporary in _names(recovery):
                    recovery.delete(temporary)
        except all_errors as recovery_error:
            retained = ", ".join(settings.directory + "/" + backups[n] for n in originals)
            detail = (" Previous files may be retained at: " + retained) if publishing and retained else ""
            raise OSError("FTP failed and cleanup could not finish. Reconnect and inspect the folder."
                          + detail) from recovery_error
        finally:
            if recovery is not None:
                recovery.close()
        raise error
    finally:
        ftp.close()
