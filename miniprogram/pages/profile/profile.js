const api = require("../../utils/api");
Page({
  data: {
    quota: { left: 0, limit: 0 },
    wallet: { credits: 0, plan: "free" },
    isAdmin: false,
    canClaim: false
  },
  onShow() {
    api.quota().then(q => this.setData({ quota: q })).catch(() => {});
    api.wallet().then(w => this.setData({ wallet: w })).catch(() => {});
    api.adminMe().then(m => this.setData({
      isAdmin: !!m.is_admin,
      canClaim: !!m.can_claim
    })).catch(() => {});
  },
  goBenefits() { wx.switchTab({ url: "/pages/benefits/benefits" }); },
  goLibrary() { wx.switchTab({ url: "/pages/library/library" }); },
  goUpload() { wx.navigateTo({ url: "/pages/upload/upload" }); },
  goKeys() { wx.navigateTo({ url: "/pages/keys/keys" }); },
  goAdmin() { wx.navigateTo({ url: "/pages/admin/admin" }); }
});
