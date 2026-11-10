const api = require("./utils/api");

App({
  globalData: {
    userId: ""
  },
  onLaunch(options) {
    const q = (options && options.query) || {};
    const invite = String(q.invite || "").trim().toUpperCase();
    if (invite) wx.setStorageSync("pending_invite", invite);
    api.login().then(() => {
      this.globalData.userId = api.getUserId();
      this.bindPendingInvite();
    }).catch(() => {});
  },
  onShow(options) {
    const q = (options && options.query) || {};
    const invite = String(q.invite || "").trim().toUpperCase();
    if (invite) wx.setStorageSync("pending_invite", invite);
    this.bindPendingInvite();
  },
  bindPendingInvite() {
    const code = wx.getStorageSync("pending_invite");
    if (!code || this._binding) return;
    this._binding = true;
    api.bindInvite(code).then(r => {
      wx.removeStorageSync("pending_invite");
      if (!r.already) wx.showToast({ title: "邀请奖励 +3 次", icon: "none" });
    }).catch(e => {
      if (["TOO_LATE", "INVALID_CODE", "SELF_INVITE"].indexOf(e.code) >= 0) {
        wx.removeStorageSync("pending_invite");
      }
    }).then(() => { this._binding = false; }, () => { this._binding = false; });
  }
});
