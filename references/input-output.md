# 输入输出与可执行命令

Python 3.11+。以下命令中的 `<skill>` 和 `<private>` 由模型替换为真实绝对路径；URL 在 JSON 文件中，不传入命令参数。用当前环境可用的 venv/uv 创建隔离环境：

```sh
uv venv <private>/.venv
uv pip install --python <private>/.venv/bin/python -r <skill>/requirements-skill.txt
<private>/.venv/bin/python <skill>/scripts/dicom_skill.py plan --request <private>/request.json
<private>/.venv/bin/python <skill>/scripts/dicom_skill.py download --request <private>/request.json
```

请求示例（占位符不可直接执行）：

```json
{
  "url": "https://hospital.example/PC/#/share_report?pid=PATIENT&sid=STUDY&rid=REPORT&inst=HOSPITAL&Expires=EXPIRY&Signature=SIGNATURE&download=1&view=1",
  "output_dir": "/absolute/private/downloads/exam-001",
  "platform": "radinfo",
  "include_report": false,
  "resume": false,
  "zip": true,
  "workers": 3,
  "timeout": 30,
  "deadline": 1800
}
```

字段：

| 字段 | 默认值 / 约束 |
| --- | --- |
| url | 必需，用户提供的完整有效链接；保留大小写、fragment 和签名 |
| output_dir | 必需，仓库之外的绝对路径；首次运行应为空 |
| platform | `auto`；未知同类微影站经检查后可设 `radinfo` |
| api_base | 微影可选；仅允许同主机且不降级 HTTPS 的已验证 API origin，不能含路径/查询 |
| password | 仅在平台实际需要时提供；如海纳医信分享密码 |
| raw | false；仅上游海纳医信族支持，其他平台拒绝此选项 |
| include_report | false；目前仅微影可提取所见/结论，正文仍可能有个人信息 |
| resume | false；仅微影，原 expected.json 与新清单须完全一致，现有文件重验 |
| zip | true；校验通过后打包 DICOM、validation.json、可选 report.json |
| workers | 3；微影 1–4 个线程 |
| timeout | 30 秒；单次请求超时 1–120 秒，暂时错误最多 3 次 |
| deadline | 1800 秒；1–7200 秒，旧适配器进程超时；微影在开始新图片请求前检查，正在进行的请求可能超出此预算 |

请求文件可用 `chmod 600 <private>/request.json` 保护。不要在聊天中回显真实签名。用户给的普通链接若带 Markdown 的 `\&` 转义，先还原为真实 `&`，不要重算签名。

输出：

- `dicom/series_<hash>/<hash>.dcm`：微影原始响应字节；文件名避免患者姓名和重复实例号覆盖。
- `expected.json`：本轮远端清单，含 UID、不含下载 URL。
- `status.json`：当前运行状态；失败可能保留部分文件，旧 validation/ZIP 不代表本轮成功。
- `validation.json`：逐文件 SHA-256、UID、尺寸、帧数、解码状态及序列统计。含临床元数据，只在本地保存。
- `report.json`：可选原报告字段，不额外抓取患者其他检查。
- `DICOM.zip`：上述检查成功后生成并做 CRC 验证。
- 旧适配器保留原目录结构，可能包含姓名；外围入口静默其控制台，所有医疗内容留在指定输出目录。

退出码：0 表示命令所声明的阶段成功；2 表示失败；`plan` 的 0 不表示下载成功。

已有目录可离线校验：

```sh
<python> <skill>/scripts/dicom_skill.py inspect <dicom-directory> --output <private>/validation.json
<python> <skill>/scripts/dicom_skill.py inspect <dicom-directory> --expected <private>/expected.json --output <private>/validation.json
```

`--expected` 接受列表或带 `files` 的校验文档，每项必须有 `sop_uid`，可有 `series_uid`、`study_uid`、`sha256`。没有期望清单时不得声称完整性已证实。`--metadata-only` 仅用于排查缺少解码器，不满足完整验收。
