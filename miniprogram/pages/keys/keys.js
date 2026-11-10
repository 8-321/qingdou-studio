const api = require("../../utils/api");

Page({
  data: {
    features: [], keyCards: [], providers: { asr: [], llm: [] },
    providerList: [], sheet: false, kind: "asr", provider: "", apiKey: "",
    baseUrl: "", model: "", saving: false
  },
  onShow() { this.load(); },
  load() {
    Promise.all([api.features(), api.keys()]).then(([f, k]) => {
      const keys = k.items || [];
      const byKind = {};
      keys.forEach(item => { byKind[item.kind] = item; });
      this.setData({
        features: f.items || [],
        keys,
        byKind,
        keyCards: [
          { kind: "asr", badge: "ASR", title: "语音转写", desc: "火山引擎 / OpenAI Whisper / 硅基流动", key: byKind.asr || null },
          { kind: "llm", badge: "LLM", title: "文案模型", desc: "DeepSeek / 混元 / 通义千问", key: byKind.llm || null }
        ],
        providers: k.providers || { asr: [], llm: [] }
      });
    }).catch(e => wx.showToast({ title: e.msg || "加载失败", icon: "none" }));
  },
  openSheet(e) {
    const kind = e.currentTarget.dataset.kind || "asr";
    const list = (this.data.providers && this.data.providers[kind]) || [];
    const existing = (this.data.byKind || {})[kind];
    const preset = existing
      ? (list.find(x => x.id === existing.provider) || list[0] || {})
      : (list[0] || {});
    this.setData({
      sheet: true, kind, providerList: list,
      provider: existing ? existing.provider : (preset.id || "custom"),
      apiKey: "",
      baseUrl: existing ? existing.base_url : (preset.base_url || ""),
      model: existing ? existing.model : (preset.model || "")
    });
  },
  closeSheet() { if (!this.data.saving) this.setData({ sheet: false }); },
  noop() {},
  pickProvider(e) {
    const id = e.currentTarget.dataset.id;
    const p = (this.data.providerList || []).find(x => x.id === id) || {};
    this.setData({ provider: id, baseUrl: p.base_url || "", model: p.model || "" });
  },
  onKey(e) { this.setData({ apiKey: e.detail.value }); },
  onBase(e) { this.setData({ baseUrl: e.detail.value }); },
  onModel(e) { this.setData({ model: e.detail.value }); },
  save() {
    const apiKey = (this.data.apiKey || "").trim();
    if (apiKey.length < 8) return wx.showToast({ title: "Key 太短", icon: "none" });
    this.setData({ saving: true });
    api.saveKey({
      kind: this.data.kind,
      provider: this.data.provider,
      api_key: apiKey,
      base_url: (this.data.baseUrl || "").trim() || undefined,
      model: (this.data.model || "").trim() || undefined
    }).then(() => {
      this.setData({ saving: false, sheet: false, apiKey: "" });
      wx.showToast({ title: "已加密保存" });
      this.load();
    }).catch(e => {
      this.setData({ saving: false });
      wx.showModal({ title: "保存失败", content: e.msg || "请检查 Key 和网络", showCancel: false });
    });
  },
  testKey(e) {
    wx.showLoading({ title: "测试中" });
    api.testKey(e.currentTarget.dataset.id).then(r => {
      wx.hideLoading();
      wx.showModal({ title: r.ok ? "连接正常" : "连接失败", content: r.msg || "服务商返回异常", showCancel: false });
      this.load();
    }).catch(err => {
      wx.hideLoading();
      wx.showModal({ title: "连接失败", content: err.msg || "服务商返回异常", showCancel: false });
    });
  },
  removeKey(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除这个密钥？",
      content: "删除后该功能会回到平台默认额度。",
      success: r => {
        if (!r.confirm) return;
        api.deleteKey(id).then(() => { wx.showToast({ title: "已删除" }); this.load(); })
          .catch(err => wx.showToast({ title: err.msg || "删除失败", icon: "none" }));
      }
    });
  },
  goBenefits() { wx.switchTab({ url: "/pages/benefits/benefits" }); }
});
