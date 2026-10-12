# Modified in local Skill fork: optional query parameters.
import re

from yarl import URL

from crawlers._utils import new_http_client
from crawlers.hinacom import HinacomDownloader

# 元素属性很简单，就直接正则了，懒得再下个解析库。
_hidden_input_re = re.compile(r'<input type="hidden" id="StudyId" name="StudyId" value="([^"]+)" />')


async def run(share_url, *args):
	address = URL(share_url)

	async with new_http_client() as client:
		# Local fork: do not turn hidden fields into a way around a visible identity check.
		if address.query.get("idType") == "accessionnumber":
			raise ValueError("Complete the site's verification and provide an authorized viewer link.")

		# 影像查看页的 URL 作为入口，从 returnUrl 回到跳转页来进入。
		if address.query.get("returnUrl"):
			share_url = address.query.get("returnUrl")

		async with await HinacomDownloader.from_viewer_link(client, share_url) as downloader:
			await downloader.download_all("--raw" in args)
