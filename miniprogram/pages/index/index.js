const api = require("../../utils/api");

Page({
  data: {
    text: "", tasks: [], quota: { left: 0, limit: 0 }, trial: { left: 2, free: 2 },
    loading: false,
    platforms: ["抖音", "小红书", "快手", "B站", "视频号", "公众号", "录音", "相册"]
  },
  onShow() { this.refresh(); },
  refresh() {
    api.quota().then(q => this.setData({ quota: q })).catch(() => {});
    api.tasks().then(r => this.setData({ tasks: r.items || [] })).catch(() => {});
    api.features().then(r => {
      const item = (r.items || []).find(x => x.feature === "link_extract");
      if (item) this.setData({ trial: item });
    }).catch(() => {});
  },
  onInput(e) { this.setData({ text: e.detail.value }); },
  goLibrary() { wx.switchTab({ url: "/pages/library/library" }); },
  goBenefits() { wx.switchTab({ url: "/pages/benefits/benefits" }); },
  goKeys() { wx.navigateTo({ url: "/pages/keys/keys" }); },
  onParse() {
    const text = (this.data.text || "").trim();
    if (!text) return wx.showToast({ title: "先粘贴链接", icon: "none" });
    this.setData({ loading: true });
    api.parse(text).then(r => {
      this.setData({ loading: false, text: "" });
      wx.navigateTo({ url: "/pages/result/result?taskId=" + r.task_id });
    }).catch(err => {
      this.setData({ loading: false });
      if (err.code === "TRIAL_ENDED") {
        return wx.showModal({
          title: "2 次免费体验用完了",
          content: "配置自己的 API Key 继续免费，或用签到 / 会员补充次数。",
          confirmText: "配置 Key",
          cancelText: "看福利",
          success: res => res.confirm ? this.goKeys() : this.goBenefits()
        });
      }
      if (err.code === "CONTENT_RISKY") {
        return wx.showModal({
          title: "内容未通过安全检测",
          content: "换一段内容再试。本次没有扣次数。",
          showCancel: false
        });
      }
      if (err.code === "QUOTA_EXCEEDED") {
        return wx.showModal({
          title: "今日次数用完了", content: "签到或看视频可再加 1 次。",
          confirmText: "去福利", showCancel: false, success: () => this.goBenefits()
        });
      }
      wx.showModal({
        title: "没提取成功", content: err.msg || "请改用上传",
        confirmText: "去上传", success: res => {
          if (res.confirm) wx.navigateTo({ url: "/pages/upload/upload" });
        }
      });
    });
  },
  openTask(e) { wx.navigateTo({ url: "/pages/result/result?taskId=" + e.currentTarget.dataset.id }); }
});
