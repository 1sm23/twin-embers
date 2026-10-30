import argparse
import hashlib
from ftplib import all_errors
import getpass
import json
from pathlib import Path
from .build import build
from . import gen4_sprites
from .rom import load_rom, SUPPORTED_SHA1
from .pak import PakReader, PakError


def main() -> None:
    parser = argparse.ArgumentParser(prog='firered3ds-builder',
                                     description='Builds twinembers.pak from your own Pokemon FireRed ROM')
    sub = parser.add_subparsers(dest='command', required=True)
    verify = sub.add_parser('verify-rom', help='check that a ROM is the supported dump')
    verify.add_argument('rom', type=Path)
    inspect = sub.add_parser('inspect-rom', help='identify a ROM and report native compatibility without building')
    inspect.add_argument('rom', type=Path)
    inspect.add_argument('--compare', action='store_true', help='compare resource records to the US recipe')
    make = sub.add_parser('build', help='create the data pack the 3DS game reads')
    make.add_argument('--rom', type=Path, required=True)
    make.add_argument('--output', type=Path, default=Path('twinembers.pak'))
    make.add_argument('--recipe', type=Path, help=argparse.SUPPRESS)
    make.add_argument('--gen4-sprites', action='store_true',
                      help='also download HeartGold battle sprites (optional, needs internet)')
    pack = sub.add_parser('verify-pak', help='check every payload of an existing pack')
    pack.add_argument('pak', type=Path)
    pack.add_argument('--abi', type=lambda s: int(s, 16), required=True)
    ftp = sub.add_parser('upload', help='wirelessly install local files on a 3DS running ftpd')
    ftp.add_argument('--host', required=True, help='3DS IP address, without ftp://')
    ftp.add_argument('--port', type=int, default=5000)
    ftp.add_argument('--user', default='anonymous')
    ftp.add_argument('--ask-password', action='store_true', help='prompt without echoing or saving a password')
    ftp.add_argument('--directory', default='/3ds/twinembers')
    ftp.add_argument('--pak', type=Path)
    ftp.add_argument('--game', type=Path, help='local twinembers.3dsx')
    ftp.add_argument('--overwrite', action='store_true', help='replace installed game files; saves are untouched')
    args = parser.parse_args()
    try:
        if args.command == 'inspect-rom':
            from .rom_info import inspect_rom
            print(json.dumps(inspect_rom(args.rom, compare=args.compare), ensure_ascii=True, indent=2))
        elif args.command == 'verify-rom':
            print(f'ROM verified: {load_rom(args.rom).sha1}')
        elif args.command == 'build':
            rom = load_rom(args.rom)
            print(f'ROM verified: {rom.sha1}')
            extra = []
            if args.gen4_sprites:
                extra, info = gen4_sprites.pack_files(gen4_sprites.Downloader(gen4_sprites.cache_dir()))
                print(f"HeartGold battle sprites: {info['species']} species "
                      f"({info['downloaded']} files downloaded), {len(info['missing'])} missing")
            result = build(args.rom, args.recipe, args.output, extra)
            digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
            print(f"Wrote {args.output}: {result['entries']} entries, {args.output.stat().st_size} bytes, "
                  f"engine ABI {result['abi']:08x}, SHA-256 {digest}")
            print('Copy it to /3ds/twinembers/twinembers.pak on the SD card.')
        elif args.command == 'upload':
            from .ftp_install import FTPSettings, upload_files
            files = {}
            if args.pak:
                files['twinembers.pak'] = args.pak
            if args.game:
                files['twinembers.3dsx'] = args.game
            settings = FTPSettings(args.host, args.port, args.user,
                                   getpass.getpass('FTP password: ') if args.ask_password else '',
                                   args.directory)
            report = upload_files(settings, files, overwrite=args.overwrite,
                                  on_progress=lambda step, msg: print(msg))
            print('Installed: ' + ', '.join(report['files']))
            for warning in report['warnings']:
                print(warning)
        else:
            with PakReader(args.pak, args.abi, bytes.fromhex(SUPPORTED_SHA1)) as reader:
                print(f'Verified {reader.verify()} payloads')
    except (ValueError, OSError, KeyError, TypeError, IndexError, PakError, *all_errors) as exc:
        parser.exit(1, f'builder: {exc}\n')
