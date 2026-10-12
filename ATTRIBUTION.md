# 来源与许可

本项目基于 [Kaciras/cloud-dicom-downloader](https://github.com/Kaciras/cloud-dicom-downloader) 改写。上游基线提交：`f77568cbda18788df92a9d9b92c9de99c07753c7`。保留原作者 Kaciras 的归属及完整 [LICENSE](LICENSE)。

许可证是 Apache License 2.0 附带 Commons Clause 条件；不能只按纯 Apache-2.0 理解或分发。许可条件以 LICENSE 原文为准。

本地修改：新增面向模型的 Skill、微影/Radinfo 适配器、下载完整性验证及结构化输入输出；修正若干上游工具、错误处理和测试。修改文件带有说明，具体修正和验证范围见 [Review](references/review.md)。

GitHub 独立仓库从经检查的当前文件创建新历史；不上传上游原始网络样本的历史。测试 fixture 为合成数据，案例仅保留技术流程、序列统计和验证结果，不包含真实患者身份、分享参数、医学报告正文或 DICOM 文件。
