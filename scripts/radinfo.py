"""微影/Radinfo share_report adapter, adapted from the 2026-10 local MRI case.

Never executes viewer JavaScript. Only understands the documented observed literals.
"""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from dicom_core import SkillError


def split_url(url):
    try:
        value = urllib.parse.urlsplit(url)
        if value.scheme not in ('http', 'https') or not value.hostname or value.username or value.password:
            raise ValueError()
        _ = value.port
        return value
    except (ValueError, TypeError) as exc:
        raise SkillError('Expected an HTTP(S) URL without embedded username/password.') from exc


def same_host(url, reference):
    a, b = split_url(url), split_url(reference)
    if a.hostname != b.hostname or (b.scheme == 'https' and a.scheme != 'https'):
        raise SkillError('Unexpected cross-host URL or HTTPS downgrade; inspect the platform before continuing.')
    return url


class GuardRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        same_host(newurl, req.full_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(GuardRedirect())

    def get(self, url, limit=20 * 1024 * 1024):
        split_url(url)
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'cloud-dicom-downloader-skill/1.0'})
                with self.opener.open(request, timeout=self.timeout) as response:
                    data = response.read(limit + 1)
                    if len(data) > limit:
                        raise SkillError('Response exceeds the configured size limit.')
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise SkillError('Access denied or expired link. Obtain a current authorized link/login.') from None
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise SkillError(f'HTTP request failed (status {exc.code}); response body omitted.') from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise SkillError('Network/TLS request failed after bounded retries.') from None
            time.sleep(attempt + 1)


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script':
            source = dict(attrs).get('src')
            if source:
                self.sources.append(source)


def share_parameters(url):
    parsed = split_url(url)
    if 'share_report' not in parsed.fragment.split('?')[0]:
        raise SkillError('This adapter expects a #/share_report link.')
    query = urllib.parse.parse_qs(parsed.fragment.partition('?')[2], keep_blank_values=True)
    if any(len(v) != 1 for v in query.values()):
        raise SkillError('Ambiguous duplicate share parameters.')
    query = {k: v[0] for k, v in query.items()}
    if query.get('download') == '0' or query.get('view') == '0':
        raise SkillError('The share link explicitly disables download or viewing.')
    result = {
        'accessionNumber': query.get('sid', ''), 'resultsIndex': query.get('rid', ''),
        'phoneNum': query.get('tel', ''), 'patientsId': query.get('pid', ''),
        'download': query.get('download', '1'), 'forward': query.get('forward', ''),
        'inst': query.get('inst', ''), 'Expires': query.get('expires', query.get('Expires', '')),
        'Signature': query.get('sign', query.get('Signature', '')),
    }
    if query.get('reid'):
        result['resultsExchangeIndex'] = query['reid']
    if not all(result[k] for k in ('accessionNumber', 'patientsId', 'Expires', 'Signature')):
        raise SkillError('Missing signed share parameters; use the complete original URL.')
    return result


def discover_api(client, url):
    parsed = split_url(url)
    page = urllib.parse.urlunsplit(parsed._replace(fragment=''))
    parser = ScriptSources()
    parser.feed(client.get(page).decode('utf-8'))
    for source in parser.sources[:8]:
        script_url = urllib.parse.urljoin(page, source)
        same_host(script_url, url)
        script = client.get(script_url).decode('utf-8')
        match = re.search(r'\bSERVER_URL\s*:\s*["\']([^"\']+)["\']', script)
        if match:
            return same_host(match[1], url).rstrip('/')
    raise SkillError('SERVER_URL not found. Inspect the page configuration; supply verified api_base.')


def literal_fields(line):
    # Only parse JSON-compatible string literals; never eval/execute page content.
    pairs = re.findall(r'"([A-Za-z][A-Za-z0-9]*)"\s*:\s*("(?:\\.|[^"\\])*")', line)
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise SkillError('Duplicate field in viewer inventory.')
        try:
            fields[key] = json.loads(value)
        except ValueError:
            raise SkillError('Unsupported viewer string encoding.') from None
    return fields


def image_url(raw, api_base):
    raw = html.unescape(raw)
    parsed = split_url(raw)
    base = split_url(api_base)
    if parsed.hostname == 'localhost' and parsed.port == 1000 and base.hostname == 'yyx.zy91.com':
        # This exact deployment exposes the viewer's server-local route on its API origin.
        if parsed.path != '/api/Wado/ImageReader':
            raise SkillError('Unrecognized server-local image path.')
        return api_base.rstrip('/') + parsed.path + '?' + parsed.query
    return same_host(raw, api_base)


def parse_inventory(text, api_base, study_uid):
    series, images, seen = {}, [], set()
    for match in re.finditer(r'var\s+serInfo(\d+)\s*=\s*([^;]+);', text):
        fields = literal_fields(match[2])
        if not fields.get('serInstUID'):
            raise SkillError('Series UID missing in viewer inventory.')
        if match[1] in series:
            raise SkillError('Duplicate series declaration.')
        series[match[1]] = fields
    declarations = list(re.finditer(r'var\s+imgInfo\d+\s*=\s*([^;]+);', text))
    announced = re.findall(r'\b(?:var|let|const)\s+imgInfo\d+\s*=', text)
    if len(announced) != len(declarations):
        raise SkillError('Unsupported image declaration; parser must be updated.')
    for match in declarations:
        line = match[1]
        refs = set(re.findall(r'serObj(\d+)\.', line))
        if len(refs) != 1 or next(iter(refs)) not in series:
            raise SkillError('Cannot associate an image with exactly one series.')
        fields = literal_fields(line)
        info = series[next(iter(refs))]
        if not all(fields.get(k) for k in ('sopInstUID', 'imageURL', 'imageNumber')):
            raise SkillError('Image inventory is missing required fields.')
        uid = fields['sopInstUID']
        if uid in seen:
            raise SkillError('Duplicate SOP UID in viewer inventory.')
        seen.add(uid)
        series_key = hashlib.sha256(info['serInstUID'].encode()).hexdigest()[:16]
        image_key = hashlib.sha256(uid.encode()).hexdigest()[:24]
        # Hashes avoid collisions from repeated InstanceNumber and untrusted path components.
        images.append({
            'sop_uid': uid, 'series_uid': info['serInstUID'], 'study_uid': study_uid,
            'path': f'dicom/series_{series_key}/{image_key}.dcm',
            'url': image_url(fields['imageURL'], api_base),
        })
    counts = re.findall(r'记录数[：:]\s*(\d+)', text)
    if not images or not series or len(images) != len(declarations):
        raise SkillError('No supported complete image inventory was parsed.')
    if counts and any(int(n) != len(images) for n in counts):
        raise SkillError('Viewer image count differs from the parsed inventory; update the parser.')
    if len({x['series_uid'] for x in images}) != len(series):
        raise SkillError('Viewer contains an empty or duplicate series; inspect before downloading.')
    return images


def prepare(request, client):
    url = request['url']
    params = share_parameters(url)
    api_base = request.get('api_base') or discover_api(client, url)
    same_host(api_base, url)
    api_base = api_base.rstrip('/')
    parsed = split_url(api_base)
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise SkillError('api_base must be a verified origin without path/query.')
    report_url = api_base + '/api/OAuth/User/StudyReport?' + urllib.parse.urlencode(params)
    try:
        response = json.loads(client.get(report_url))
    except ValueError:
        raise SkillError('Report endpoint did not return JSON.') from None
    if response.get('success') is not True or not isinstance(response.get('data'), dict):
        raise SkillError('Report access was not successful; verify link/login. Server details omitted.')
    report = response['data']
    viewer = report.get('ViewerUrl')
    study = report.get('StudiesInstUID')
    if not viewer or not study:
        raise SkillError('Report has no viewer URL or study UID.')
    same_host(viewer, api_base)
    inventory = parse_inventory(client.get(viewer).decode('utf-8'), api_base, study)
    return inventory, {
        'source': 'hospital_report_api',
        'findings': report.get('ReportsEvidences') or '',
        'conclusion': report.get('ReportsConclusion') or '',
        'note': 'Original report fields; not an independent image diagnosis. May contain personal data.',
    }
