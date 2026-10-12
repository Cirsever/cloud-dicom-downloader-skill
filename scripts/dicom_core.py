"""Local DICOM integrity checks; no network and no diagnostic interpretation."""
import hashlib
import io
import json
import os
from pathlib import Path

import pydicom


class SkillError(Exception):
    """Message must be safe to expose (no source URL, server body, or patient data)."""


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temporary.replace(path)


def check_dicom(data, expected=None, decode=True):
    try:
        ds = pydicom.dcmread(io.BytesIO(data))
        uid = str(ds.SOPInstanceUID)
        series = str(ds.SeriesInstanceUID)
        study = str(ds.StudyInstanceUID)
        if not uid or not series or not study:
            raise ValueError('empty UID')
        if str(ds.file_meta.MediaStorageSOPInstanceUID) != uid:
            raise ValueError('file meta UID mismatch')
        if str(ds.file_meta.MediaStorageSOPClassUID) != str(ds.SOPClassUID):
            raise ValueError('file meta class mismatch')
        if expected:
            for key, actual in [('sop_uid', uid), ('series_uid', series), ('study_uid', study)]:
                if expected.get(key) and expected[key] != actual:
                    raise SkillError('DICOM UID differs from the requested image; stopped.')
        if decode:
            pixels = ds.pixel_array
            frames = int(ds.get('NumberOfFrames', 1))
            shape = (int(ds.Rows), int(ds.Columns))
            if int(ds.SamplesPerPixel) > 1:
                shape += (int(ds.SamplesPerPixel),)
            if frames > 1:
                shape = (frames,) + shape
            if pixels.shape != shape or pixels.size == 0:
                raise SkillError('Decoded pixel dimensions do not match DICOM metadata.')
        return {
            'sop_uid': uid, 'series_uid': series, 'study_uid': study,
            'modality': str(ds.get('Modality', '')),
            'series_number': str(ds.get('SeriesNumber', '')),
            'series_description': str(ds.get('SeriesDescription', '')),
            'instance_number': str(ds.get('InstanceNumber', '')),
            'rows': int(ds.Rows), 'columns': int(ds.Columns),
            'samples_per_pixel': int(ds.SamplesPerPixel),
            'frames': int(ds.get('NumberOfFrames', 1)),
            'transfer_syntax': str(ds.file_meta.TransferSyntaxUID),
            'pixels_decoded': decode, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }
    except SkillError:
        raise
    except RuntimeError as exc:
        raise SkillError('Pixel decoding failed; install the required codec and revalidate.') from exc
    except Exception as exc:
        raise SkillError('Invalid, truncated, or unsupported DICOM data.') from exc


def inspect_directory(root, expected=None, decode=True):
    root = Path(root).resolve()
    if not root.is_dir():
        raise SkillError('DICOM directory does not exist.')
    files = sorted(p for p in root.rglob('*') if p.suffix.lower() == '.dcm')
    if not files:
        raise SkillError('No DICOM files found.')
    targets = None
    if expected is not None:
        targets = {x['sop_uid']: x for x in expected}
        if len(targets) != len(expected):
            raise SkillError('Expected inventory contains duplicate SOP UIDs.')
    seen, records = set(), []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SkillError('Symlinked DICOM files are not accepted.')
        data = path.read_bytes()
        record = check_dicom(data, decode=decode)
        uid = record['sop_uid']
        if uid in seen:
            raise SkillError('Duplicate SOP UID found in local files.')
        seen.add(uid)
        if targets is not None:
            if uid not in targets:
                raise SkillError('Local image is absent from the expected inventory.')
            check_dicom(data, expected=targets[uid], decode=False)
            if targets[uid].get('sha256') and record['sha256'] != targets[uid]['sha256']:
                raise SkillError('Local file checksum differs from the expected manifest.')
        record['path'] = str(path.relative_to(root))
        records.append(record)
    if targets is not None and seen != set(targets):
        raise SkillError('Local download is incomplete relative to the expected inventory.')
    groups = {}
    for record in records:
        key = record['series_uid']
        if key not in groups:
            groups[key] = {k: record[k] for k in ['series_uid', 'series_number', 'series_description', 'modality']}
            groups[key]['instances'] = 0
            groups[key]['frames'] = 0
        groups[key]['instances'] += 1
        groups[key]['frames'] += record['frames']
    return {
        'schema_version': 1,
        'status': 'verified' if decode else 'metadata_only',
        'completeness': 'matches_expected_inventory' if targets is not None else 'unknown_no_remote_inventory',
        'instances': len(records), 'frames': sum(x['frames'] for x in records),
        'series_count': len(groups), 'bytes': sum(x['bytes'] for x in records),
        'all_pixels_decoded': decode, 'series': list(groups.values()), 'files': records,
    }
