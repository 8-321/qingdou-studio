const BASE_URL = "http://127.0.0.1:8788";
const DEV_USER_ID = "demo";
const LOCAL = /127\.0\.0\.1|localhost/i.test(BASE_URL);
const TOKEN_KEY = "auth_token";
const UID_KEY = "auth_uid";

let token = wx.getStorageSync(TOKEN_KEY) || "";
let userId = wx.getStorageSync(UID_KEY) || "";
let devFallback = false;
let loginPromise = null;

function saveAuth(data) {
  token = data.token || "";
  userId = data.user_id || "";
  devFallback = false;
  wx.setStorageSync(TOKEN_KEY, token);
  wx.setStorageSync(UID_KEY, userId);
}

function clearAuth() {
  token = "";
  userId = "";
  wx.removeStorageSync(TOKEN_KEY);
  wx.removeStorageSync(UID_KEY);
}

function headers(extra) {
  const h = Object.assign({ "content-type": "application/json" }, extra || {});
  if (token) h.Authorization = "Bearer " + token;
  else if (devFallback) h["X-User-Id"] = DEV_USER_ID;
  return h;
}

function wxRequest(path, method, data, header) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + path,
      method: method || "GET",
      data,
      header,
      timeout: 30000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data);
        const detail = (res.data && res.data.detail) || {};
        reject({
          status: res.statusCode,
          code: detail.code || "HTTP_" + res.statusCode,
          msg: detail.msg || "请求失败",
          raw: detail
        });
      },
      fail() {
        reject({ code: "NETWORK", msg: "网络异常，请检查服务是否启动" });
      }
    });
  });
}

function login(force) {
  if (token && !force) return Promise.resolve();
  if (loginPromise) return loginPromise;
  loginPromise = new Promise((resolve, reject) => {
    wx.login({
      success(r) {
        wxRequest("/api/auth/wechat", "POST", { code: r.code, platform: "mp" },
          { "content-type": "application/json" })
          .then(data => { saveAuth(data); resolve(); })
          .catch(err => {
            if (LOCAL) {
              devFallback = true;
              userId = DEV_USER_ID;
              resolve();
              return;
            }
            reject(err);
          });
      },
      fail(err) {
        if (LOCAL) {
          devFallback = true;
          userId = DEV_USER_ID;
          resolve();
          return;
        }
        reject({ code: "WX_LOGIN_FAIL", msg: "微信登录失败，请重试" });
      }
    });
  }).then(() => { loginPromise = null; }, e => { loginPromise = null; throw e; });
  return loginPromise;
}

function request(path, method = "GET", data) {
  return login().then(() => wxRequest(path, method, data, headers()))
    .catch(err => {
      if (err && err.status === 401) {
        clearAuth();
        return login(true).then(() => wxRequest(path, method, data, headers()));
      }
      throw err;
    });
}

module.exports = {
  BASE_URL,
  login,
  logout() { clearAuth(); devFallback = false; },
  getUserId() { return userId; },
  isDevFallback() { return devFallback; },
  me: () => request("/api/auth/me"),
  parse: (text) => request("/api/parse", "POST", { text }),
  task: (id) => request("/api/tasks/" + id),
  result: (id) => request("/api/tasks/" + id + "/result"),
  rewrite: (id, style, refresh) =>
    request("/api/tasks/" + id + "/rewrite", "POST", { style, refresh: !!refresh }),
  quota: () => request("/api/quota"),
  signin: () => request("/api/signin", "POST", {}),
  tasks(opts) {
    const q = opts || {};
    const parts = [];
    ["q", "platform", "status", "tag"].forEach(k => {
      if (q[k]) parts.push(k + "=" + encodeURIComponent(q[k]));
    });
    if (q.fav) parts.push("fav=1");
    if (q.sort && q.sort !== "new") parts.push("sort=" + q.sort);
    if (q.limit) parts.push("limit=" + q.limit);
    if (q.offset) parts.push("offset=" + q.offset);
    return request("/api/tasks" + (parts.length ? "?" + parts.join("&") : ""));
  },
  taskTags: () => request("/api/task-tags"),
  patchTask: (id, body) => request("/api/tasks/" + id, "PATCH", body),
  removeTask: (id) => request("/api/tasks/" + id, "DELETE"),
  features: () => request("/api/features"),
  products: () => request("/api/products"),
  wallet: () => request("/api/wallet"),
  createOrder: (productId) => request("/api/orders", "POST", { product_id: productId }),
  mockPay: (orderId) => request("/api/orders/" + orderId + "/mock-pay", "POST", {}),
  redeem: (code) => request("/api/redeem", "POST", { code }),
  invite: () => request("/api/invite"),
  bindInvite: (code) => request("/api/invite/bind", "POST", { code }),
  rewards: () => request("/api/rewards"),
  adStart: () => request("/api/rewards/ad/start", "POST", {}),
  adFinish: (token) => request("/api/rewards/ad/finish", "POST", { token }),
  keys: () => request("/api/keys"),
  saveKey: (body) => request("/api/keys", "POST", body),
  testKey: (id) => request("/api/keys/" + id + "/test", "POST", {}),
  deleteKey: (id) => request("/api/keys/" + id, "DELETE"),
  adminMe: () => request("/api/admin/me"),
  adminClaim: () => request("/api/admin/claim", "POST", {}),
  adminMobile: () => request("/api/admin/mobile"),
  adminConfig: () => request("/api/admin/config"),
  adminGrowth: () => request("/api/admin/growth"),
  adminSetGrowth: (ad_reward_daily) =>
    request("/api/admin/growth", "POST", { ad_reward_daily }),
  adminSetConfig: (feature, free_tries) =>
    request("/api/admin/config", "POST", { feature, free_tries }),
  adminUsers: (q) => request("/api/admin/users?q=" + encodeURIComponent(q || "")),
  adminUser: (id) => request("/api/admin/users/" + encodeURIComponent(id)),
  adminGrant: (body) => request("/api/admin/grants", "POST", body),
  adminCredits: (user_id, amount, reason) =>
    request("/api/admin/credits", "POST", { user_id, amount, reason: reason || "移动后台调整" }),
  adminPlan: (user_id, plan, days) =>
    request("/api/admin/plan", "POST", { user_id, plan, days }),
  adminAdmins: () => request("/api/admin/admins"),
  adminAddAdmin: (user_id, note) =>
    request("/api/admin/admins", "POST", { user_id, note: note || "移动后台添加" }),
  adminRemoveAdmin: (id) => request("/api/admin/admins/" + encodeURIComponent(id), "DELETE"),
  adminRedeem: () => request("/api/admin/redeem"),
  adminCreateRedeem: (body) => request("/api/admin/redeem", "POST", body),
  adminAudit: () => request("/api/admin/audit"),
  exportFile(id, fmt) {
    return login().then(() => new Promise((resolve, reject) => {
      wx.downloadFile({
        url: BASE_URL + "/api/tasks/" + id + "/export?fmt=" + fmt,
        header: headers({}),
        timeout: 60000,
        success(res) {
          if (res.statusCode === 200) return resolve(res.tempFilePath);
          reject({ code: "EXPORT_" + res.statusCode, msg: "导出失败，请稍后重试" });
        },
        fail() { reject({ code: "NETWORK", msg: "导出失败，请检查网络" }); }
      });
    }));
  },
  nameFile(tempPath, filename) {
    return new Promise((resolve) => {
      const fs = wx.getFileSystemManager();
      const safe = String(filename || "export").replace(/[\\/:*?"<>|\r\n]/g, " ").trim().slice(0, 60) || "export";
      const target = wx.env.USER_DATA_PATH + "/" + safe;
      fs.unlink({ filePath: target, fail() {} });
      fs.copyFile({
        srcPath: tempPath, destPath: target,
        success: () => resolve(target),
        fail: () => resolve(tempPath)
      });
    });
  },
  readText(path) {
    return new Promise((resolve, reject) => {
      wx.getFileSystemManager().readFile({
        filePath: path, encoding: "utf8",
        success: r => resolve(r.data),
        fail: () => reject({ msg: "读取导出文件失败" })
      });
    });
  },
  batchExport(ids, fmt, zip) {
    const ext = zip ? "zip" : fmt;
    return login().then(() => new Promise((resolve, reject) => {
      wx.request({
        url: BASE_URL + "/api/export/batch",
        method: "POST",
        data: { ids, fmt, zip: !!zip },
        header: headers(),
        responseType: "arraybuffer",
        timeout: 60000,
        success(res) {
          if (res.statusCode !== 200) {
            let msg = "导出失败";
            try {
              const body = JSON.parse(String.fromCharCode.apply(null, new Uint8Array(res.data)));
              msg = (body.detail && body.detail.msg) || msg;
            } catch (e) {}
            return reject({ code: "EXPORT_" + res.statusCode, msg });
          }
          const path = wx.env.USER_DATA_PATH + "/export-" + Date.now() + "." + ext;
          wx.getFileSystemManager().writeFile({
            filePath: path, data: res.data, encoding: "binary",
            success: () => resolve(path),
            fail: () => reject({ msg: "写入导出文件失败" })
          });
        },
        fail() { reject({ code: "NETWORK", msg: "导出失败，请检查网络" }); }
      });
    }));
  },
  openDoc(path, ext) {
    return new Promise((resolve, reject) => {
      wx.openDocument({
        filePath: path, fileType: ext, showMenu: true,
        success: resolve,
        fail: () => reject({ msg: "打开失败，请确认手机已安装 WPS 或 Office" })
      });
    });
  },
  shareFile(path, name) {
    if (!wx.shareFileMessage) return Promise.reject({ msg: "当前微信版本不支持文件分享" });
    return new Promise((resolve, reject) => {
      wx.shareFileMessage({
        filePath: path, fileName: name,
        success: resolve,
        fail: () => reject({ msg: "分享已取消" })
      });
    });
  },
  upload(filePath, onProgress) {
    return login().then(() => new Promise((resolve, reject) => {
      const task = wx.uploadFile({
        url: BASE_URL + "/api/upload/simple",
        filePath,
        name: "file",
        header: headers({}),
        success(res) {
          try {
            const body = JSON.parse(res.data);
            if (res.statusCode === 200) return resolve(body);
            reject((body.detail) || { msg: "上传失败" });
          } catch (e) { reject({ msg: "上传响应异常" }); }
        },
        fail() { reject({ msg: "上传失败" }); }
      });
      if (task && task.onProgressUpdate && onProgress) {
        task.onProgressUpdate(r => onProgress(r.progress || 0));
      }
    }));
  }
};
