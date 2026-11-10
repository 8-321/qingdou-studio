const api = require("../../utils/api");

const ORDER = ["byok_year", "byok_month", "credits_300", "credits_3600", "credits_30", "team_month"];

Page({
  data: {
    quota: { left: 0, limit: 0, signed: false },
    products: [], plan: "free", planUntil: "", credits: 0,
    selected: "credits_300", ios: false, code: "", loading: false,
    invite: { code: "", invited: 0, rewarded: 0, reward_days: 0 },
    rewards: { enabled: false, daily_limit: 5, used_today: 0, left_today: 0, min_seconds: 15 },
    inviteInput: "", adLoading: false
  },
  onLoad() {
    try { this.setData({ ios: wx.getSystemInfoSync().platform === "ios" }); } catch (e) {}
  },
  onShow() { this.refresh(); },
  refresh() {
    api.quota().then(q => this.setData({ quota: q })).catch(() => {});
    api.products().then(r => {
      const list = (r.items || []).sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
      this.setData({ products: list });
    }).catch(() => {});
    api.wallet().then(w => this.setData({
      credits: w.credits || 0, plan: w.plan || "free", planUntil: w.plan_until || ""
    })).catch(() => {});
    api.invite().then(v => this.setData({ invite: v })).catch(() => {});
    api.rewards().then(v => this.setData({ rewards: v })).catch(() => {});
  },
  signin() {
    api.signin().then(q => {
      this.setData({ quota: q });
      wx.showToast({ title: "签到 +1 次" });
      this.refresh();
    }).catch(e => wx.showToast({ title: e.msg || "今天已签到", icon: "none" }));
  },
  pickProduct(e) { this.setData({ selected: e.currentTarget.dataset.id }); },
  pay() {
    if (this.data.ios) {
      return wx.showModal({
        title: "iOS 暂不支持购买",
        content: "苹果规则不允许小程序内卖虚拟服务。请用兑换码，或到安卓端 / APP 开通。",
        showCancel: false
      });
    }
    const p = (this.data.products || []).find(x => x.id === this.data.selected);
    if (!p) return wx.showToast({ title: "先选一个套餐", icon: "none" });
    this.setData({ loading: true });
    api.createOrder(p.id).then(res => {
      const pay = res.pay || {};
      if (pay.mode === "mock") {
        return api.mockPay(res.order.id).then(r => {
          this.setData({ loading: false });
          wx.showModal({
            title: "已到账",
            content: p.credits ? ("已增加 " + p.credits + " 次额度") : ("已开通 " + p.name),
            showCancel: false
          });
          this.refresh();
        });
      }
      if (pay.mode === "jsapi" && pay.pay_params) {
        return new Promise((resolve, reject) => {
          wx.requestPayment({
            ...pay.pay_params,
            success: resolve,
            fail: reject
          });
        }).then(() => {
          this.setData({ loading: false });
          wx.showToast({ title: "支付成功" });
          this.refresh();
        });
      }
      this.setData({ loading: false });
      if (pay.mode === "native" && pay.code_url) {
        return wx.showModal({ title: "请在浏览器打开支付", content: pay.code_url, showCancel: false });
      }
      wx.showModal({ title: "暂时无法支付", content: pay.msg || "请使用兑换码", showCancel: false });
    }).catch(e => {
      this.setData({ loading: false });
      wx.showModal({ title: "下单失败", content: e.msg || "请稍后再试", showCancel: false });
    });
  },
  onCode(e) { this.setData({ code: e.detail.value }); },
  redeem() {
    const code = (this.data.code || "").trim();
    if (!code) return wx.showToast({ title: "先填兑换码", icon: "none" });
    api.redeem(code).then(r => {
      this.setData({ code: "" });
      wx.showModal({
        title: "兑换成功",
        content: r.product.credits ? ("已到账 " + r.product.credits + " 次") : ("已开通 " + r.product.name),
        showCancel: false
      });
      this.refresh();
    }).catch(e => wx.showModal({ title: "兑换失败", content: e.msg || "兑换码无效", showCancel: false }));
  },
  onInviteInput(e) { this.setData({ inviteInput: e.detail.value }); },
  copyInvite() {
    const code = this.data.invite.code;
    if (!code) return;
    wx.setClipboardData({ data: code, success: () => wx.showToast({ title: "邀请码已复制" }) });
  },
  bindInvite() {
    const code = (this.data.inviteInput || "").trim();
    if (!code) return wx.showToast({ title: "先填邀请码", icon: "none" });
    api.bindInvite(code).then(r => {
      this.setData({ inviteInput: "" });
      wx.showModal({
        title: r.already ? "已经绑定过" : "绑定成功",
        content: r.already ? "这个账号已经绑定过邀请人" : "你和好友各得 3 次链接提取",
        showCancel: false
      });
      this.refresh();
    }).catch(e => wx.showModal({ title: "绑定失败", content: e.msg || "邀请码无效", showCancel: false }));
  },
  watchAd() {
    const r = this.data.rewards || {};
    if (!r.enabled) {
      return wx.showModal({ title: "激励视频未开通", content: "广告位还没配置。可以先用签到或邀请领次数。", showCancel: false });
    }
    if ((r.left_today || 0) <= 0) return wx.showToast({ title: "今天领完了", icon: "none" });
    if (this.data.adLoading) return;
    this.setData({ adLoading: true });
    api.adStart().then(res => this.playAd(res.token)).catch(e => {
      this.setData({ adLoading: false });
      wx.showToast({ title: e.msg || "暂时没法播放", icon: "none" });
    });
  },
  playAd(token) {
    if (!this._ad) {
      this._ad = wx.createRewardedVideoAd({ adUnitId: this.data.rewards.ad_unit_id });
    }
    const finish = (res) => {
      this._ad.offClose(finish);
      if (!res || !res.isEnded) {
        this.setData({ adLoading: false });
        return wx.showToast({ title: "完整看完才有奖励", icon: "none" });
      }
      api.adFinish(token).then(v => {
        this.setData({ adLoading: false, rewards: v });
        wx.showToast({ title: "奖励 +1 次" });
        this.refresh();
      }).catch(e => {
        this.setData({ adLoading: false });
        wx.showToast({ title: e.msg || "领取失败", icon: "none" });
      });
    };
    this._ad.onClose(finish);
    this._ad.show().catch(() => this._ad.load().then(() => this._ad.show()).catch(() => {
      this._ad.offClose(finish);
      this.setData({ adLoading: false });
      wx.showModal({ title: "广告加载失败", content: "稍后再试，或先用签到 / 邀请领次数。", showCancel: false });
    }));
  },
  onShareAppMessage() {
    const code = (this.data.invite && this.data.invite.code) || "";
    return {
      title: "把任何视频、录音变成逐句稿，双方各得 3 次",
      path: "/pages/index/index" + (code ? "?invite=" + code : "")
    };
  }
});
