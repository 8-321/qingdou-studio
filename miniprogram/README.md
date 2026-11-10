# 小程序骨架（微信原生）

## 导入

1. 打开微信开发者工具 → 导入项目 → 选择 `E:\轻抖复刻\06-代码\miniprogram`
2. AppID 先选"测试号"或填自己的
3. 详情 → 本地设置 → 勾选 **不校验合法域名**（因为后端是 `http://127.0.0.1:8788`）
4. 先启动后端（见 `../server/README.md`），再编译

## 页面

| 页面 | 功能 |
|---|---|
| `pages/index` | 粘贴链接、额度、最近任务 |
| `pages/keys` | API 密钥：免费额度、ASR/LLM Key、测试/删除 |
| `pages/result` | 逐句稿 / 结构卡 / 复制 / SRT |
| `pages/upload` | 相册视频、聊天文件 |
| `pages/library` | 素材库 |
| `pages/benefits` | 签到、会员、邀请 |
| `pages/profile` | 我的 |

## 改后端地址

`utils/api.js` 第一行：

```js
const BASE_URL = "http://127.0.0.1:8788";
```

上线改成 `https://api.你的域名.com`，并在公众平台配置 request/uploadFile 合法域名。

## 尚未实现（骨架只到能跑）

- 微信登录（code2session）
- 登录：已接 `wx.login` → `/api/auth/wechat` → 30 天 token；服务端没配 AppID/Secret 时，仅本地 `127.0.0.1` 会回退到演示身份 `demo`
- 上线前：把 `utils/api.js` 的 `BASE_URL` 换成 HTTPS 域名，并在小程序后台把该域名加入 request 合法域名
- 支付（wx.requestPayment）
- 激励视频广告
- 分片续传（小程序端先用 `uploadFile` 简单上传）
- 订阅消息通知
- 内容安全校验（服务端做）
