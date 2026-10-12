"""Synthetic-only regression tests. No patient data and no external network."""
import io
import json
from pathlib import Path
import sys
import urllib.error
import zipfile

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dicom_skill as cli
from dicom_core import SkillError, check_dicom, inspect_directory
import radinfo

STUDY = '1.2.826.0.1.3680043.10.999.1'
SERIES = STUDY + '.1'
SOP = SERIES + '.1'
URL = 'https://yyx.zy91.com:6443/PC/#/share_report?pid=DEMO&sid=DEMO&rid=DEMO&Expires=9999999999&Signature=DEMO&download=1&view=1'


def dicom(uid=SOP, rgb=False, frames=1):
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = uid
    ds.StudyInstanceUID = STUDY
    ds.SeriesInstanceUID = SERIES
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.Modality = 'MR'
    ds.SeriesNumber = 1
    ds.SeriesDescription = 'SYNTHETIC'
    ds.InstanceNumber = 1
    ds.Rows, ds.Columns = 2, 3
    ds.SamplesPerPixel = 3 if rgb else 1
    ds.PhotometricInterpretation = 'RGB' if rgb else 'MONOCHROME2'
    if rgb:
        ds.PlanarConfiguration = 0
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    if frames > 1:
        ds.NumberOfFrames = frames
    ds.PixelData = bytes(range(6 * ds.SamplesPerPixel * frames))
    stream = io.BytesIO()
    ds.save_as(stream, enforce_file_format=True)
    return stream.getvalue()


def viewer(count=1, uid=SOP, raw='http://localhost:1000/api/Wado/ImageReader?FN=SYNTHETIC'):
    return f'''console.log('记录数：{count}');
var serInfo0 = '{{ "patIndex":' + studyObj.patIndex + ', "serInstUID":"{SERIES}", "serNumber":"1" }}';
var imgInfo00 = '{{ "patIndex":' + serObj0.patIndex + ', "serIndex":' + serObj0.serIndex + ', "sopInstUID":"{uid}", "imageURL":"{raw}", "imageNumber":"1" }}';'''


@pytest.mark.parametrize('rgb,frames', [(False, 1), (True, 1), (False, 2), (True, 2)])
def test_decode_shapes(rgb, frames):
    record = check_dicom(dicom(rgb=rgb, frames=frames))
    assert record['frames'] == frames
    assert record['pixels_decoded'] is True


def test_invalid_uid_and_fake_dicom():
    with pytest.raises(SkillError, match='UID differs'):
        check_dicom(dicom(), {'sop_uid': SOP + '.9'})
    with pytest.raises(SkillError):
        check_dicom(b'<html>login required</html>')
    with pytest.raises(SkillError):
        check_dicom(dicom()[:-20])


def test_parser_counts_mapping_and_duplicate():
    images = radinfo.parse_inventory(viewer(), 'https://yyx.zy91.com:5443', STUDY)
    assert images[0]['url'].startswith('https://yyx.zy91.com:5443/api/Wado/ImageReader?')
    assert images[0]['sop_uid'] == SOP
    with pytest.raises(SkillError, match='count differs'):
        radinfo.parse_inventory(viewer(count=2), 'https://yyx.zy91.com:5443', STUDY)
    with pytest.raises(SkillError, match='Duplicate'):
        radinfo.parse_inventory(viewer() + viewer(), 'https://yyx.zy91.com:5443', STUDY)


def test_same_instance_number_has_unique_paths():
    text = viewer(count=2)
    line = text.splitlines()[-1].replace('imgInfo00', 'imgInfo01').replace(f'"{SOP}"', f'"{SOP}.2"')
    images = radinfo.parse_inventory(text + '\n' + line, 'https://yyx.zy91.com:5443', STUDY)
    assert images[0]['path'] != images[1]['path']


@pytest.mark.parametrize('raw', ['http://localhost:1000/secret', 'https://evil.example/api', 'http://yyx.zy91.com/api'])
def test_unexpected_image_addresses(raw):
    with pytest.raises(SkillError):
        radinfo.parse_inventory(viewer(raw=raw), 'https://yyx.zy91.com:5443', STUDY)


def test_no_general_localhost_mapping():
    with pytest.raises(SkillError):
        radinfo.parse_inventory(viewer(), 'https://hospital.example', STUDY)


def test_input_route_privacy_and_download_permission(tmp_path):
    assert cli.platform_for({'url': URL}) == 'radinfo'
    assert cli.platform_for({'url': 'https://demo.medicalimagecloud.com/t/demo'}) == 'hinacom'
    for url in ['file:///tmp/data', 'https://medicalimagecloud.com.evil.example/t/demo']:
        with pytest.raises(SkillError):
            cli.platform_for({'url': url})
    with pytest.raises(SkillError, match='disables'):
        radinfo.share_parameters(URL.replace('download=1', 'download=0'))
    with pytest.raises(SkillError, match='duplicate'):
        radinfo.share_parameters(URL + '&pid=OTHER')
    with pytest.raises(SkillError):
        cli.output_root({'output_dir': str(cli.ROOT / 'download')})


def test_local_inventory_missing_extra_duplicate(tmp_path):
    (tmp_path / '1.dcm').write_bytes(dicom())
    expected = [{'sop_uid': SOP, 'series_uid': SERIES, 'study_uid': STUDY}]
    result = inspect_directory(tmp_path, expected)
    assert result['completeness'] == 'matches_expected_inventory'
    assert inspect_directory(tmp_path)['completeness'] == 'unknown_no_remote_inventory'
    with pytest.raises(SkillError, match='incomplete'):
        inspect_directory(tmp_path, expected + [{'sop_uid': SOP + '.2'}])
    (tmp_path / '2.dcm').write_bytes(dicom())
    with pytest.raises(SkillError, match='Duplicate'):
        inspect_directory(tmp_path)


def test_http_retry_and_no_sensitive_error(monkeypatch):
    calls = []
    class Opener:
        def open(self, *args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError('https://example.org?token=SECRET', 403, 'PATIENT', {}, None)
    client = radinfo.Client()
    client.opener = Opener()
    with pytest.raises(SkillError) as error:
        client.get('https://example.org?token=SECRET')
    assert len(calls) == 1
    assert 'SECRET' not in str(error.value) and 'PATIENT' not in str(error.value)


def test_end_to_end_download_resume_and_report(tmp_path, monkeypatch):
    calls = []
    def get(self, url, limit=None):
        calls.append(url)
        if 'ImageReader' in url:
            return dicom()
        if '/api/OAuth/' in url:
            return json.dumps({'success': True, 'data': {'StudiesInstUID': STUDY,
                'ViewerUrl': 'https://yyx.zy91.com:5443/WebView',
                'ReportsEvidences': 'Synthetic findings', 'ReportsConclusion': 'Synthetic conclusion'}}).encode()
        if '/WebView' in url:
            return viewer().encode()
        if 'app.js' in url:
            return b'var config={SERVER_URL:"https://yyx.zy91.com:5443/"};'
        return b'<script src="/app.js"></script>'
    monkeypatch.setattr(radinfo.Client, 'get', get)
    output = tmp_path / 'download'
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps({'url': URL, 'output_dir': str(output), 'include_report': True}))
    request = cli.read_request(request_path)
    result = cli.download(request, request_path)
    assert result['instances'] == 1 and result['all_pixels_decoded'] is True
    assert json.loads((output / 'report.json').read_text())['conclusion'] == 'Synthetic conclusion'
    with zipfile.ZipFile(output / 'DICOM.zip') as archive:
        assert archive.testzip() is None
        assert len([p for p in archive.namelist() if p.endswith('.dcm')]) == 1
    for path in output.glob('*.json'):
        assert 'Signature' not in path.read_text() and 'ImageReader' not in path.read_text()
    request['resume'] = True
    request['include_report'] = False
    cli.download(request, request_path)
    assert sum('ImageReader' in x for x in calls) == 1
    with zipfile.ZipFile(output / 'DICOM.zip') as archive:
        assert 'report.json' not in archive.namelist()
    image = next(output.rglob('*.dcm'))
    image.write_bytes(b'broken')
    with pytest.raises(SkillError):
        cli.download(request, request_path)
    assert json.loads((output / 'status.json').read_text())['status'] == 'failed'
    assert not (output / '.download.lock').exists()


def test_upstream_conversion_roundtrip(tmp_path):
    from tools.export import SliceList
    for name, array in [('gray', np.zeros((2, 3), dtype=np.uint8)), ('rgb', np.zeros((2, 3, 3), dtype=np.uint8))]:
        dest = tmp_path / name
        SliceList([array]).to_dcm_files(dest)
        data = next(dest.rglob('*.dcm')).read_bytes()
        ds = pydicom.dcmread(io.BytesIO(data))
        assert ds.pixel_array.shape == array.shape


def test_retry_budget_for_transient_http(monkeypatch):
    calls = []
    class Opener:
        def open(self, *args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError('https://example.org?token=SECRET', 503, 'PRIVATE', {}, None)
    client = radinfo.Client()
    client.opener = Opener()
    monkeypatch.setattr(radinfo.time, 'sleep', lambda _: None)
    with pytest.raises(SkillError, match='503'):
        client.get('https://example.org')
    assert len(calls) == 3


def test_resume_rejects_changed_inventory(tmp_path, monkeypatch):
    target = tmp_path / 'output'
    target.mkdir()
    (target / 'expected.json').write_text('[]')
    request = {'url': URL, 'output_dir': str(target), 'resume': True, 'timeout': 30, 'deadline': 30, 'workers': 1}
    monkeypatch.setattr(cli, 'prepare', lambda *args: ([{'sop_uid': SOP, 'path': 'dicom/1.dcm', 'url': 'https://example.org'}], {}))
    with pytest.raises(SkillError, match='differs'):
        cli.download(request, tmp_path / 'unused.json')
    assert json.loads((target / 'status.json').read_text())['status'] == 'failed'


def test_metadata_only_does_not_claim_pixel_decode(tmp_path):
    (tmp_path / 'image.dcm').write_bytes(dicom())
    result = inspect_directory(tmp_path, decode=False)
    assert result['status'] == 'metadata_only'
    assert result['all_pixels_decoded'] is False


def test_guard_redirect_rejects_foreign_host():
    import urllib.request
    req = urllib.request.Request('https://example.org/viewer')
    with pytest.raises(SkillError):
        radinfo.GuardRedirect().redirect_request(req, None, 302, 'redirect', {}, 'https://other.example/steal')


def test_symlink_dicom_is_rejected(tmp_path):
    original = tmp_path / 'original.dcm'
    original.write_bytes(dicom())
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'linked.dcm').symlink_to(original)
    with pytest.raises(SkillError, match='Symlink'):
        inspect_directory(folder)


def test_empty_series_and_missing_optional_name(tmp_path):
    from crawlers._utils import SeriesDirectory, suggest_series_name
    assert suggest_series_name(Dataset()) == 'Unnamed'
    assert SeriesDirectory(tmp_path, 1, '', 0).get(0, 'dcm').name.endswith('.dcm')
