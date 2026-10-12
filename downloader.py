# Modified in local Skill fork: validated arguments, lazy imports, safe errors.
"""Legacy positional interface. Agents should use scripts/dicom_skill.py instead."""
import argparse
import asyncio
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'scripts'))
from dicom_core import SkillError
from dicom_skill import platform_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('password', nargs='?')
    parser.add_argument('--raw', action='store_true')
    args = parser.parse_args()
    try:
        name = platform_for({'url': args.url})
        if name == 'radinfo':
            raise SkillError('Radinfo requires scripts/dicom_skill.py download --request <private-request.json>.')
        if name == 'hinacom' and not args.password:
            raise SkillError('This platform requires its share password.')
        if args.password and name != 'hinacom':
            raise SkillError('This platform does not accept a positional password.')
        if args.raw and name not in ('hinacom', 'cq12320', 'jdyfy'):
            raise SkillError('raw is only supported by the Hinacom family.')
        values = [args.url] + ([args.password] if args.password else []) + (['--raw'] if args.raw else [])
        print('Legacy mode: local file verification must be run separately with the Skill inspect command.')
        asyncio.run(importlib.import_module('crawlers.' + name).run(*values))
        return 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print('Legacy download failed; inspect locally without publishing credentials or medical data.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
