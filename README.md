<!-- Modified in local Skill fork: new agent-facing entrypoint and validation contract. -->
# cloud-dicom-downloader Skill

将 [Kaciras/cloud-dicom-downloader](https://github.com/Kaciras/cloud-dicom-downloader) 改写为面向大模型的 CT/MRI 云影像下载 Skill。入口为 [SKILL.md](SKILL.md)，包含用户输入示例、平台路由、实际执行命令、下载完整性验证和报告解释流程。

新增微影/Radinfo 场景（yyx.zy91.com），保留 10 个上游平台适配模块。新下载入口为 `scripts/dicom_skill.py`；原 `downloader.py` 保留为兼容入口。完整性主张与平台测试范围见 [平台表](references/platforms.md)。

## 使用

向支持 Skill 的模型说：

> 使用 $cloud-dicom-downloader 下载这个 MRI 分享链接中的 DICOM，保存报告，并解释报告结论：<完整链接>

或只要求下载影像。模型按 Skill 安装 `requirements-skill.txt`，把 URL 放在仓库外的私有 JSON 文件中，再执行：

```sh
python /path/to/skill/scripts/dicom_skill.py plan --request /private/request.json
python /path/to/skill/scripts/dicom_skill.py download --request /private/request.json
```

[请求 JSON 和输出契约](references/input-output.md) · [微影案例](references/radinfo-case.md) · [项目 Review](references/review.md)

可将此整个目录放入宿主的 skills 目录，目录名为 `cloud-dicom-downloader`；或在本机建立指向此目录的符号链接。Skill 本身不包含患者数据、账号凭证或影像。Python 环境和下载产物保存在仓库之外。

## 开发和验证

```sh
python -m pip install -r requirements-test.txt
python -m pytest
```

合成测试无需医院链接。实网回归需用户授权的有效链接；不得把私人样本作为 fixture 提交。继承适配器的站点可用性没有在本轮全部实网验证。

## 来源和许可

上游基线：`f77568cbda18788df92a9d9b92c9de99c07753c7`。本地分支：`codex/ct-mri-skill`，远端 `upstream` 指向原项目。GitHub 独立仓库：[Cirsever/cloud-dicom-downloader-skill](https://github.com/Cirsever/cloud-dicom-downloader-skill)。远端 `main` 从已检查的当前文件建立独立根提交，避免携带上游原始网络样本的历史；上游历史仅保留在本地。来源及修改说明见 [ATTRIBUTION.md](ATTRIBUTION.md)。

完整保留 [LICENSE](LICENSE)：Apache License 2.0 **附带 Commons Clause 条件**。不是单纯 Apache-2.0；分发时保留完整条件和上游归属。具体权利义务以原许可证文本为准。
