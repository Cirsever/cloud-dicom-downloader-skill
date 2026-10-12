#!/usr/bin/env python3
"""Skill-facing entrypoint; credentials enter through a local request file."""
import argparse
import concurrent.futures
import importlib
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import time
import zipfile

from dicom_core import SkillError, check_dicom, inspect_directory, write_json
from radinfo import Client, prepare, split_url

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    'mdmis.cq12320.cn': 'cq12320', 'qr.szjudianyun.com': 'szjudianyun',
    'ylyyx.shdc.org.cn': 'shdc', 'zscloud.zs-hospital.sh.cn': 'zscloud',
    'app.ftimage.cn': 'ftimage', 'yyx.ftimage.cn': 'ftimage',
    'm.yzhcloud.com': 'yzhcloud', 'ss.mtywcloud.com': 'mtywcloud',
    'work.sugh.net': 'sugh', 'cloudpacs.jdyfy.com': 'jdyfy',
    'yyx.zy91.com': 'radinfo',
}


def platform_for(request):
    host = split_url(request['url']).hostname
    automatic = 'hinacom' if host.endswith('.medicalimagecloud.com') else PLATFORMS.get(host)
    explicit = request.get('platform', 'auto')
    if explicit == 'radinfo':
        return 'radinfo'
    if explicit != 'auto' and explicit != automatic:
        raise SkillError('Explicit platform does not match the supported host.')
    if not automatic:
        raise SkillError('Unsupported host. Inspect it using references/new-platform.md; no download attempted.')
    return automatic


def read_request(path):
    try:
        request = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise SkillError('Cannot read request JSON.') from None
    allowed = {'url', 'output_dir', 'platform', 'api_base', 'password', 'raw', 'include_report',
               'resume', 'zip', 'timeout', 'deadline', 'workers'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise SkillError('Unknown request fields; see references/input-output.md.')
    if not isinstance(request.get('url'), str) or not isinstance(request.get('output_dir'), str):
        raise SkillError('Request requires string url and output_dir fields.')
    for key in ('raw', 'include_report', 'resume', 'zip'):
        if key in request and not isinstance(request[key], bool):
            raise SkillError('Boolean request options must be JSON true/false.')
    for key, low, high, default in [('timeout', 1, 120, 30), ('deadline', 1, 7200, 1800), ('workers', 1, 4, 3)]:
        value = request.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise SkillError(f'{key} must be an integer between {low} and {high}.')
        request[key] = value
    for key in ('platform', 'api_base', 'password'):
        if key in request and not isinstance(request[key], str):
            raise SkillError('Platform, API origin, and password must be strings.')
    if request.get('platform') is None:
        request['platform'] = 'auto'
    return request


def output_root(request):
    root = Path(request['output_dir']).expanduser()
    if not root.is_absolute():
        raise SkillError('output_dir must be an absolute path outside the Skill repository.')
    if root.is_symlink():
        raise SkillError('Output directory must not be a symlink.')
    root = root.resolve()
    if root.is_relative_to(ROOT) or ROOT.is_relative_to(root):
        raise SkillError('Keep medical output outside the Skill repository and its parent directories.')
    return root


def legacy_worker(request_path):
    request = read_request(request_path)
    name = platform_for(request)
    if name == 'radinfo':
        raise SkillError('Invalid legacy platform.')
    root = output_root(request)
    os.chdir(root)
    sys.path.insert(0, str(ROOT))
    import asyncio
    module = importlib.import_module('crawlers.' + name)
    args = [request['url']]
    if name == 'hinacom':
        if not request.get('password'):
            raise SkillError('This platform requires the report password.')
        args.append(request['password'])
    if request.get('raw'):
        if name not in ('hinacom', 'cq12320', 'jdyfy'):
            raise SkillError('raw is only supported by the Hinacom family.')
        args.append('--raw')
    asyncio.run(module.run(*args))


def package(root, validation, include_report=False):
    target = root / 'DICOM.zip'
    temporary = root / 'DICOM.zip.part'
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in validation['files']:
            archive.write(root / item['path'], item['path'])
        archive.write(root / 'validation.json', 'validation.json')
        if include_report and (root / 'report.json').is_file():
            archive.write(root / 'report.json', 'report.json')
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise SkillError('ZIP CRC verification failed.')
    os.chmod(temporary, 0o600)
    temporary.replace(target)


def download(request, request_path):
    name, root = platform_for(request), output_root(request)
    if name == 'radinfo' and request.get('raw'):
        raise SkillError('Radinfo saves server DICOM bytes unchanged; raw is not a supported option.')
    if name == 'hinacom' and not request.get('password'):
        raise SkillError('This platform requires the report password.')
    if name != 'radinfo' and request.get('resume'):
        raise SkillError('Legacy adapters do not support verified resume; use a fresh output directory.')
    if request.get('include_report') and name != 'radinfo':
        raise SkillError('Structured report extraction is currently implemented only for Radinfo.')
    if root.exists() and any(root.iterdir()) and not request.get('resume'):
        raise SkillError('Output is nonempty; choose a new directory or use verified Radinfo resume.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # No same-directory concurrent runs; never silently remove another run's lock.
    lock = root / '.download.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SkillError('Output is locked by a download; inspect the existing run before removing its lock.') from None
    os.close(fd)
    try:
        return _download_locked(request, request_path, name, root)
    except Exception:
        write_json(root / 'status.json', {'status': 'failed', 'complete': False, 'message': 'Download or validation failed; files may be partial.'})
        raise
    finally:
        lock.unlink(missing_ok=True)


def _download_locked(request, request_path, name, root):
    started = time.monotonic()
    if name != 'radinfo':
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), '_legacy', '--request', str(Path(request_path).resolve())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=(os.name == 'posix'),
        )
        try:
            returncode = process.wait(timeout=request['deadline'])
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
            raise SkillError('Legacy adapter exceeded its deadline; output may be partial.') from None
        if returncode:
            raise SkillError('Legacy adapter failed. No success claimed; inspect platform access and local files.')
        validation = inspect_directory(root)
    else:
        inventory, report = prepare(request, Client(request['timeout']))
        expected = [{k: v for k, v in image.items() if k != 'url'} for image in inventory]
        if request.get('resume') and (root / 'expected.json').exists():
            previous = json.loads((root / 'expected.json').read_text())
            if previous != expected:
                raise SkillError('Resume inventory differs from the previous run; use a fresh directory.')
        elif request.get('resume') and any(p != root / '.download.lock' for p in root.iterdir()):
            raise SkillError('Cannot resume without the matching expected inventory.')
        write_json(root / 'expected.json', expected)
        write_json(root / 'status.json', {'status': 'downloading', 'expected_instances': len(expected), 'completed': 0})
        if request.get('include_report'):
            write_json(root / 'report.json', report)

        def fetch(image):
            if time.monotonic() - started > request['deadline']:
                raise SkillError('Download deadline reached; partial files can be resumed.')
            target = root / image['path']
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                raise SkillError('Unsafe output path.')
            if target.exists():
                check_dicom(target.read_bytes(), image)
                return
            data = Client(request['timeout']).get(image['url'], limit=256 * 1024 * 1024)
            check_dicom(data, image)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = target.with_suffix('.part')
            with temporary.open('wb') as stream:
                os.chmod(temporary, 0o600)
                stream.write(data)
            temporary.replace(target)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=request['workers'])
        futures = [pool.submit(fetch, image) for image in inventory]
        done = 0
        try:
            for future in concurrent.futures.as_completed(futures):
                future.result()
                done += 1
                write_json(root / 'status.json', {'status': 'downloading', 'expected_instances': len(expected), 'completed': done})
                if done % 20 == 0:
                    print(json.dumps({'event': 'progress', 'completed': done, 'expected': len(expected)}), flush=True)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        validation = inspect_directory(root, expected)
    write_json(root / 'validation.json', validation)
    if request.get('zip', True):
        package(root, validation, include_report=request.get('include_report', False))
    status = {k: validation[k] for k in ('status', 'completeness', 'instances', 'series_count', 'all_pixels_decoded')}
    status['platform'] = name
    write_json(root / 'status.json', status)
    return status


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'download', '_legacy'):
        command = sub.add_parser(name)
        command.add_argument('--request', required=True)
    command = sub.add_parser('inspect')
    command.add_argument('directory')
    command.add_argument('--expected', help='Expected inventory JSON or existing validation JSON with files.')
    command.add_argument('--output', required=True)
    command.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'inspect':
            if Path(args.output).resolve().is_relative_to(ROOT):
                raise SkillError('Keep validation output outside the Skill repository.')
            expected = json.loads(Path(args.expected).read_text()) if args.expected else None
            if isinstance(expected, dict):
                expected = expected['files']
            result = inspect_directory(args.directory, expected, decode=not args.metadata_only)
            write_json(args.output, result)
            print(json.dumps({k: result[k] for k in ('status', 'completeness', 'instances', 'series_count', 'all_pixels_decoded')}))
        elif args.command == '_legacy':
            legacy_worker(args.request)
        else:
            request = read_request(args.request)
            if args.command == 'plan':
                name = platform_for(request)
                output_root(request)
                print(json.dumps({'platform': name, 'network_accessed': False,
                    'remote_inventory_validation': name == 'radinfo',
                    'report_extraction': name == 'radinfo',
                    'password_required': name == 'hinacom'}))
            else:
                result = download(request, args.request)
                print(json.dumps(result))
        return 0
    except (SkillError, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, SkillError) else 'Input or local I/O error; details omitted to avoid exposing medical data.'
        print(json.dumps({'status': 'failed', 'message': message}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({'status': 'failed', 'message': 'Unexpected adapter failure; no success claimed. Inspect locally without sharing raw logs.'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
