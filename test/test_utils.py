# Modified in local Skill fork: private-error behavior and ephemeral test port.
from pathlib import Path

import pytest
from aiohttp import web, ClientResponseError
from pytest import mark

# noinspection PyProtectedMember
from crawlers._utils import pathify, new_http_client, make_unique_dir


@mark.parametrize('text, expected', [
	['|*?"', "｜＊？'"],
	[' p/a\\t/h ', 'p／a＼t／h'],
	['Size > 5', 'Size ＞ 5', ],
	['Size < 5', 'Size ＜ 5', ],
	['Recon 2: 5mm', 'Recon 2： 5mm'],
])
def test_pathify(text, expected):
	assert pathify(text) == expected


async def hello(_):
	return web.Response(status=500, text='Hello, world')


async def test_response_does_not_dump_sensitive_data(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	app = web.Application()
	app.router.add_get('/', hello)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, '127.0.0.1', 0)
	await site.start()
	port = site._server.sockets[0].getsockname()[1]
	try:
		async with new_http_client() as client:
			with pytest.raises(RuntimeError, match="status 500"):
				await client.get(f"http://127.0.0.1:{port}")
		assert not Path("dump.zip").exists()
	finally:
		await runner.cleanup()


def test_make_unique_dir():
	path = Path("download/__test_dir")
	created = make_unique_dir(path)
	try:
		assert created.is_dir()
		assert created == path
	finally:
		created.rmdir()


def test_make_unique_dir_2():
	already_exists = Path("download/__test_dir (1)")
	already_exists.mkdir(parents=True)
	try:
		created = make_unique_dir(already_exists)

		assert created.is_dir()
		assert created == Path("download/__test_dir (2)")
		created.rmdir()
	finally:
		already_exists.rmdir()


def test_make_unique_dir_3():
	already_exists = Path("download/5.0 x 5.0")
	already_exists.mkdir(parents=True)
	try:
		created = make_unique_dir(already_exists)

		assert created.is_dir()
		assert created == Path("download/5.0 x 5.0 (1)")
		created.rmdir()
	finally:
		already_exists.rmdir()
