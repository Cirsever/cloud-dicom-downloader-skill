# 平台路由与证据范围

新 Skill 入口采用延迟导入。以下保留适配器来自上游提交 `f77568cbda18788df92a9d9b92c9de99c07753c7`；有代码不表示当前线上仍有效。

| 域名 | 实现 | 输入特点 | 本地 fork 验证范围 |
| --- | --- | --- | --- |
| yyx.zy91.com | scripts/radinfo.py | PC/#/share_report 签名链接 | 本次真实 6 序列/119 实例案例 + 合成端到端测试 |
| *.medicalimagecloud.com | crawlers/hinacom.py | 分享 URL、password，可 raw | 保留；标签+像素重建 DICOM，私有标签 VR 假定 LO，非字节级原件 |
| mdmis.cq12320.cn | crawlers/cq12320.py | share_id/content | 保留；海纳医信族，无独立分享密码 |
| cloudpacs.jdyfy.com | crawlers/jdyfy.py | 上游报告/阅片链接 | 保留，补可选参数处理；实际需要验证时由用户完成，不采用页面隐藏字段绕过验证 |
| ylyyx.shdc.org.cn | crawlers/shdc.py | sid/token 或 appid/share_id | 保留；站点签名常量可能失效 |
| zscloud.zs-hospital.sh.cn | crawlers/zscloud.py | shared?code | 保留；配置解密逻辑可能漂移 |
| app.ftimage.cn / yyx.ftimage.cn | crawlers/ftimage.py | dimage 链接 | 保留；需要浏览器，可因关闭窗口/漏事件导致不完整 |
| qr.szjudianyun.com | crawlers/szjudianyun.py | a/b/c | 保留；站点 HTTP/WS，顺序协议假设需真实回归 |
| ss.mtywcloud.com | crawlers/mtywcloud.py | ICCWebClient 参数 | 保留；未本次实网验证 |
| m.yzhcloud.com | crawlers/yzhcloud.py | study_instance_uid/org_id | 保留；可能混有 PNG/JPG，现已保留扩展名，不冒充 DICOM |
| work.sugh.net | crawlers/sugh.py | clinicalShareToken | 保留；未本次实网验证 |

所有继承适配器经新入口下载后做本地 DICOM 解码、重复 UID 检查；它们尚未统一导出远端期望清单，故报告 `unknown_no_remote_inventory`。非 DICOM 附件不被 DICOM.zip 自动收录，必须单独向用户说明其存在。没有 DICOM 时明确失败，不能把截图改后缀当原始影像。

同平台新域名：`platform=radinfo` 只启用相同的解析路径，不是支持承诺。仅接受已检查的同主机地址；未知跨域/CDN 或 `localhost` 映射需先做明确适配。禁止向用户计算机 localhost 请求网页中标注的医院内网资源。

上游 README 列出的“无法下载”厂商是历史陈述，不能作为所有部署的实时事实。可检查用户授权的当前页面是否有导出功能，但不得承诺一定能恢复原始文件。
