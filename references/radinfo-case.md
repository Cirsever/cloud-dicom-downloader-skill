# 微影 / Radinfo：真实 MRI 场景的通用化

案例来源：本地一次经用户授权的 MRI 下载（2026-10-12）。可分发材料仅保留技术事实；原链接、病人 ID、UID、姓名、生日、报告原文、FN 与签名均不复制到此仓库。

## 已观测到的链路

1. PC 分享页为 SPA，片段路径 `/share_report`；参数含 pid/sid/rid/inst/Expires/Signature。通过公开加载的 app JS 中 `SERVER_URL` 定位 API origin，而非假设网页端口就是 API 端口。
2. 按页面请求结构读取 `/api/OAuth/User/StudyReport`。字段映射 pid→patientsId、sid→accessionNumber、rid→resultsIndex；保留签名和到期字段。`success=true` 后得到 `ViewerUrl`、`StudiesInstUID`，以及可选的报告所见/结论。
3. `/WebView` HTML 用 `serInfoN/serObjN`、`imgInfoN` 声明检查清单。只解析字面量，不执行 JavaScript。
4. 该部署的 imageURL 写为 `http://localhost:1000/api/Wado/ImageReader?FN=...`，这是服务器端资源标识。已验证此路径可由同一医院 API origin 返回 DICOM。映射仅对 yyx.zy91.com 此部署启用，不能泛化为任意 localhost 或任意医院端口。
5. 浏览器可经 WebSocket 阅片，但该部署无需逆向 WebSocket 像素格式，医院的 HTTP ImageReader 已返回标准 DICOM 字节。保留原响应并逐张校验。

## 本次清单与技术验证

| 序列 | 描述 | 实例数 |
| --- | --- | ---: |
| 201 | gre_scout_3pl_R | 9 |
| 301 | pd_fse_sag_fs_ACS_R | 24 |
| 401 | pd_fse_cor_fs_ACS_R | 30 |
| 501 | t2_fse_tra_fs_ACS_R | 26 |
| 601 | t1_fse_tra_ACS_R | 26 |
| 8001 | Motion Curve | 4 |

合计 119 个实例、6 个序列、18,107,536 字节。119 个 SOP UID 唯一且与阅片清单一致，序列 UID 匹配，全部像素解码成功；压缩包 CRC 通过。传输语法为 JPEG Lossless SV1（1.2.840.10008.1.2.4.70）。这说明与分享清单一致，不证明医院没有其他检查或未分享序列，也不证明已完成医学诊断。

## 从案例提炼的修正

- 不能只安装 openjpeg：此例需要 `pylibjpeg-libjpeg` 解码 JPEG Lossless。
- 不能对所有像素数组都用 `shape[-2:]`：Motion Curve 是 RGB，数组为 `(rows, columns, 3)`，另需处理多帧。
- Motion Curve 虽含在 MR 检查中，并不是解剖切片；最终描述使用“DICOM 实例”更准确。
- InstanceNumber 在不同序列甚至同一序列可重复；下载文件名用 UID 哈希，校验同时比较完整 UID。
- 可分发测试使用合成患者、合成 UID、合成像素。真实医疗文件只在用户本地数据目录做离线回归，不进入 Git 或 Skill 压缩包。
