const api = require("../../utils/api");

function shortId(id) {
  const s = String(id || "");
  return s.length > 16 ? s.slice(0, 8) + "…" + s.slice(-4) : s;
}

Page({
  data: {
    loading: true,
    me: null,
    noAuth: false,
    canClaim: false,
    tab: "overview",
    stats: {},
    features: [],
    tasks: [],
    users: [],
    admins: [],
    products: [],
    redeemCodes: [],
    audit: [],
    q: "",
    newCode: "",
    newUses: "1",
    productIndex: 0,
    newAdmin: "",
    moreLoaded: false,
    growth: { ad_reward_daily: 5, ad_enabled: false },
    saving: false
  },

  onShow() {
    this.check();
  },

  check() {
    this.setData({ loading: true });
    api.adminMe().then(me => {
      const isAdmin = !!me.is_admin;
      this.setData({ me, noAuth: !isAdmin, canClaim: !!me.can_claim, loading: false });
      if (isAdmin) this.loadMobile();
    }).catch(() => this.setData({ noAuth: true, loading: false }));
  },

  claim() {
    wx.showLoading({ title: "认领中", mask: true });
    api.adminClaim().then(() => {
      wx.hideLoading();
      wx.showToast({ title: "你已是管理员" });
      this.check();
    }).catch(e => {
      wx.hideLoading();
      wx.showModal({ title: "认领失败", content: e.msg || "请稍后再试", showCancel: false });
    });
  },

  copyId() {
    wx.setClipboardData({ data: (this.data.me && this.data.me.user_id) || "" });
  },

  loadMobile() {
    api.adminMobile().then(d => {
      const order = ["link_extract", "article_extract", "audio_extract", "video_extract"];
      const features = (d.features || []).sort(
        (a, b) => order.indexOf(a.feature) - order.indexOf(b.feature)
      );
      const today = {};
      (d.feature_today || []).forEach(x => { today[x.feature] = x.n; });
      features.forEach(f => { f.today = today[f.feature] || 0; });
      const tasks = (d.recent_tasks || []).slice(0, 6).map(t => ({
        ...t,
        short_user: shortId(t.user_id),
        short_time: String(t.created_at || "").slice(5, 16),
        label: t.status === "done" ? "完成" : t.status === "failed" ? "失败" : "处理中"
      }));
      this.setData({ stats: d.overview || {}, features, tasks });
      api.adminGrowth().then(g => this.setData({ growth: g })).catch(() => {});
    }).catch(e => wx.showToast({ title: e.msg || "加载失败", icon: "none" }));
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ tab });
    if (tab === "users" && !this.data.users.length) this.loadUsers();
    if (tab === "more" && !this.data.moreLoaded) this.loadMore();
  },

  onQ(e) { this.setData({ q: e.detail.value }); },
  search() { this.loadUsers(this.data.q); },

  loadUsers(q) {
    api.adminUsers(q || "").then(d => {
      const users = (d.items || []).map(u => ({
        ...u,
        short_user: shortId(u.id),
        plan_label: u.plan === "free" ? "免费" : u.plan === "pro" ? "会员" : u.plan
      }));
      this.setData({ users });
    }).catch(e => wx.showToast({ title: e.msg || "加载失败", icon: "none" }));
  },

  pickUser(e) {
    const uid = e.currentTarget.dataset.id;
    wx.showActionSheet({
      itemList: ["补偿 3 次", "加 / 减额度", "开通或续费会员 30 天", "查看详情"],
      success: res => {
        if (res.tapIndex === 0) this.chooseFeature(uid);
        if (res.tapIndex === 1) this.addCredits(uid);
        if (res.tapIndex === 2) this.openPlan(uid);
        if (res.tapIndex === 3) this.openUser(uid);
      }
    });
  },

  chooseFeature(uid) {
    const names = this.data.features.map(f => f.name);
    wx.showActionSheet({
      itemList: names,
      success: res => {
        const f = this.data.features[res.tapIndex];
        api.adminGrant({
          user_id: uid, feature: f.feature, extra_tries: 3, days: 0, reason: "移动后台补偿"
        }).then(() => {
          wx.showToast({ title: "已加 3 次" });
          this.loadUsers(this.data.q);
        }).catch(e => wx.showToast({ title: e.msg || "失败", icon: "none" }));
      }
    });
  },

  addCredits(uid) {
    wx.showModal({
      title: "调整额度",
      editable: true,
      placeholderText: "例如 30，负数表示扣减",
      success: res => {
        if (!res.confirm) return;
        const n = Number(res.content);
        if (!n) return wx.showToast({ title: "请输入数字", icon: "none" });
        api.adminCredits(uid, n).then(() => {
          wx.showToast({ title: "额度已更新" });
          this.loadUsers(this.data.q);
          this.loadMobile();
        }).catch(e => wx.showToast({ title: e.msg || "失败", icon: "none" }));
      }
    });
  },

  openPlan(uid) {
    wx.showModal({
      title: "开通会员",
      content: "给 " + shortId(uid) + " 开通 30 天 BYOK 会员？",
      success: res => {
        if (!res.confirm) return;
        api.adminPlan(uid, "pro", 30).then(() => {
          wx.showToast({ title: "已开通" });
          this.loadUsers(this.data.q);
        }).catch(e => wx.showToast({ title: e.msg || "失败", icon: "none" }));
      }
    });
  },

  openUser(uid) {
    api.adminUser(uid).then(d => {
      const p = d.plan || {};
      const usage = (d.usage || []).map(x => x.feature + " " + x.used + " 次").join("\n") || "无";
      wx.showModal({
        title: shortId(uid),
        content: "会员：" + (p.plan || "free") + "\n额度：" + (p.credits || 0) +
          "\n到期：" + (p.plan_until || "—") + "\n已用：\n" + usage,
        showCancel: false
      });
    }).catch(e => wx.showToast({ title: e.msg || "失败", icon: "none" }));
  },

  bumpFeature(e) {
    const i = Number(e.currentTarget.dataset.index);
    const delta = Number(e.currentTarget.dataset.delta);
    const features = this.data.features.slice();
    features[i].free_tries = Math.max(0, Math.min(100, Number(features[i].free_tries) + delta));
    this.setData({ features });
  },

  bumpGrowth(e) {
    const delta = Number(e.currentTarget.dataset.delta);
    const value = Math.max(0, Math.min(20, Number(this.data.growth.ad_reward_daily || 0) + delta));
    this.setData({ growth: Object.assign({}, this.data.growth, { ad_reward_daily: value }) });
  },

  saveGrowth() {
    api.adminSetGrowth(this.data.growth.ad_reward_daily).then(g => {
      this.setData({ growth: Object.assign({}, this.data.growth, g) });
      wx.showToast({ title: "已保存" });
    }).catch(e => wx.showToast({ title: e.msg || "保存失败", icon: "none" }));
  },

  saveFeatures() {
    if (this.data.saving) return;
    this.setData({ saving: true });
    const jobs = this.data.features.map(f => api.adminSetConfig(f.feature, f.free_tries));
    Promise.all(jobs).then(() => {
      this.setData({ saving: false });
      wx.showToast({ title: "已保存" });
      this.loadMobile();
    }).catch(e => {
      this.setData({ saving: false });
      wx.showToast({ title: e.msg || "保存失败", icon: "none" });
    });
  },

  loadMore() {
    this.setData({ moreLoaded: true });
    api.products().then(r => this.setData({ products: r.items || [] })).catch(() => {});
    api.adminAdmins().then(r => this.setData({ admins: r.items || [] })).catch(() => {});
    api.adminAudit().then(r => this.setData({ audit: (r.items || []).slice(0, 10) })).catch(() => {});
    api.adminRedeem().then(r => this.setData({ redeemCodes: (r.items || []).slice(0, 6) })).catch(() => {});
  },

  onNewCode(e) { this.setData({ newCode: e.detail.value.toUpperCase() }); },
  onNewUses(e) { this.setData({ newUses: e.detail.value }); },
  onProduct(e) { this.setData({ productIndex: Number(e.detail.value) }); },

  createRedeem() {
    const code = (this.data.newCode || "").trim();
    const p = this.data.products[this.data.productIndex];
    if (!code) return wx.showToast({ title: "先填兑换码", icon: "none" });
    if (!p) return wx.showToast({ title: "还没有商品", icon: "none" });
    api.adminCreateRedeem({
      code, product_id: p.id, max_uses: Number(this.data.newUses || 1), days: 30
    }).then(() => {
      wx.showToast({ title: "已生成" });
      this.setData({ newCode: "" });
      api.adminRedeem().then(r => this.setData({ redeemCodes: (r.items || []).slice(0, 6) })).catch(() => {});
    }).catch(e => wx.showToast({ title: e.msg || "生成失败", icon: "none" }));
  },

  onNewAdmin(e) { this.setData({ newAdmin: e.detail.value }); },

  addAdmin() {
    const uid = (this.data.newAdmin || "").trim();
    if (!uid) return wx.showToast({ title: "填对方用户 ID", icon: "none" });
    api.adminAddAdmin(uid).then(() => {
      wx.showToast({ title: "已添加" });
      this.setData({ newAdmin: "" });
      api.adminAdmins().then(r => this.setData({ admins: r.items || [] })).catch(() => {});
    }).catch(e => wx.showToast({ title: e.msg || "失败", icon: "none" }));
  },

  removeAdmin(e) {
    const uid = e.currentTarget.dataset.id;
    wx.showModal({
      title: "移除协管员",
      content: "确定移除 " + shortId(uid) + " 吗？",
      success: res => {
        if (!res.confirm) return;
        api.adminRemoveAdmin(uid).then(() => {
          wx.showToast({ title: "已移除" });
          api.adminAdmins().then(r => this.setData({ admins: r.items || [] })).catch(() => {});
        }).catch(e2 => wx.showToast({ title: e2.msg || "失败", icon: "none" }));
      }
    });
  }
});
