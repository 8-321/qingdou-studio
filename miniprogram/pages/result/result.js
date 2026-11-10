const api = require("../../utils/api");

const PLAT_TEXT = {
  douyin: "抖音", kuaishou: "快手", xiaohongshu: "小红书", bilibili: "B站",
  wechat_article: "公众号", wechat_channels: "视频号", weibo: "微博",
  ixigua: "西瓜视频", youtube: "YouTube", tiktok: "TikTok", upload: "本地上传"
};

const EXPORT_ITEMS = [
  { key: "docx", label: "Word 文档", desc: "全文 + 逐句 + 结构卡，可直接改" },
  { key: "xlsx", label: "Excel 表格", desc: "逐句时间轴，可筛选、可分工" },
  { key: "srt", label: "SRT 字幕", desc: "发给剪映 / Premiere 直接用" },
  { key: "md", label: "Markdown", desc: "复制到 Notion / 飞书 / 公众号" },
  { key: "txt", label: "纯文本", desc: "只要正文，复制即用" }
];

Page({
  data: {
    taskId: "", task: null, result: null, tab: "text", segments: [], err: "", errCode: "",
    rewrite: null, rewriting: false, rwStyle: "oral",
    fav: 0, tags: [], sheetOpen: false, exporting: false, exportText: "",
    chars: 0, durText: "0:00", exportItems: EXPORT_ITEMS
  },
  onLoad(q) {
    this.setData({ taskId: q.taskId });
    this.poll();
  },
  onUnload() { clearTimeout(this.timer); },
  poll() {
    api.task(this.data.taskId).then(t => {
      const tags = Array.isArray(t.tags) ? t.tags : [];
      this.setData({ task: t, fav: t.fav ? 1 : 0, tags });
      if (t.status === "done") return this.loadResult();
      if (t.status === "failed") {
        if (t.error_code === "SEC_RISKY" || t.error_code === "CONTENT_RISKY") {
          return this.setData({ err: "内容未通过安全检测，本次次数已自动退回。", errCode: t.error_code });
        }
        const msg = (t.error_msg || "解析失败，请改用上传").replace(/^TOO_LONG:/, "");
        return this.setData({ err: msg, errCode: t.error_code || "" });
      }
      this.timer = setTimeout(() => this.poll(), 1000);
    }).catch(e => this.setData({ err: e.msg || "任务不存在" }));
  },
  loadResult() {
    api.result(this.data.taskId).then(r => {
      const segs = (r.segments || []).map(s => Object.assign({}, s, {
        timeText: Math.floor(s.start / 60) + ":" + String(Math.floor(s.start % 60)).padStart(2, "0")
      }));
      r.platformText = PLAT_TEXT[r.platform] || r.platform;
      const chars = String(r.full_text || "").replace(/\s/g, "").length;
      const d = Math.round(r.duration_sec || 0);
      this.setData({
        result: r, segments: segs, chars,
        durText: Math.floor(d / 60) + ":" + String(d % 60).padStart(2, "0")
      });
    }).catch(e => this.setData({ err: e.msg || "读取失败" }));
  },
  switchTab(e) { this.setData({ tab: e.currentTarget.dataset.tab }); },
  copyAll() {
    const r = this.data.result;
    if (!r) return;
    wx.setClipboardData({ data: r.full_text, success: () => wx.showToast({ title: "已复制全文" }) });
  },
  copySegment(e) {
    const text = e.currentTarget.dataset.text;
    if (!text) return;
    wx.setClipboardData({ data: text, success: () => wx.showToast({ title: "已复制这一句" }) });
  },
  openSheet() { this.setData({ sheetOpen: true }); },
  closeSheet() { this.setData({ sheetOpen: false }); },
  fileTitle() {
    const t = (this.data.result && this.data.result.title) || "文案";
    return String(t).replace(/[\\/:*?"<>|\r\n]/g, " ").trim().slice(0, 40) || "文案";
  },
  busy(on, text) {
    this.setData({ exporting: !!on, exportText: text || "正在准备文件" });
    if (on) wx.showLoading({ title: text || "正在准备文件", mask: true });
    else wx.hideLoading();
  },
  pickExport(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ sheetOpen: false });
    if (key === "txt") {
      return wx.setClipboardData({
        data: (this.data.result || {}).full_text || "",
        success: () => wx.showToast({ title: "全文已复制" })
      });
    }
    if (key === "md") return this.copyExport("md", "Markdown 已复制");
    if (key === "docx" || key === "xlsx") return this.openExport(key);
    if (key === "srt") return this.shareExport("srt");
  },
  copyExport(fmt, tip) {
    this.busy(true, "正在生成");
    api.exportFile(this.data.taskId, fmt)
      .then(p => api.readText(p))
      .then(text => {
        this.busy(false);
        wx.setClipboardData({ data: text, success: () => wx.showToast({ title: tip }) });
      })
      .catch(e => { this.busy(false); wx.showToast({ title: e.msg || "导出失败", icon: "none" }); });
  },
  openExport(fmt) {
    this.busy(true, "正在生成 " + fmt.toUpperCase());
    api.exportFile(this.data.taskId, fmt)
      .then(p => api.nameFile(p, this.fileTitle() + "." + fmt))
      .then(p => api.openDoc(p, fmt))
      .then(() => this.busy(false))
      .catch(e => { this.busy(false); wx.showToast({ title: e.msg || "导出失败", icon: "none" }); });
  },
  shareExport(fmt) {
    const name = this.fileTitle() + "." + fmt;
    this.busy(true, "正在生成字幕");
    api.exportFile(this.data.taskId, fmt)
      .then(p => api.nameFile(p, name))
      .then(p => api.shareFile(p, name))
      .then(() => this.busy(false))
      .catch(e => {
        this.busy(false);
        api.exportFile(this.data.taskId, fmt)
          .then(p => api.readText(p))
          .then(text => wx.setClipboardData({
            data: text,
            success: () => wx.showToast({ title: "已复制 SRT 文本" })
          }))
          .catch(() => wx.showToast({ title: e.msg || "导出失败", icon: "none" }));
      });
  },
  toggleFav() {
    const fav = this.data.fav ? 0 : 1;
    api.patchTask(this.data.taskId, { fav })
      .then(() => {
        this.setData({ fav });
        wx.showToast({ title: fav ? "已收藏" : "已取消" });
      })
      .catch(e => wx.showToast({ title: e.msg || "操作失败", icon: "none" }));
  },
  editTags() {
    wx.showModal({
      title: "标签",
      editable: true,
      placeholderText: "空格或逗号分隔，最多 8 个",
      content: this.data.tags.join(" "),
      success: r => {
        if (!r.confirm) return;
        const tags = String(r.content || "").split(/[\s,，、]+/).filter(Boolean).slice(0, 8);
        api.patchTask(this.data.taskId, { tags })
          .then(res => {
            this.setData({ tags: res.tags || [] });
            wx.showToast({ title: tags.length ? "标签已保存" : "已清空标签" });
          })
          .catch(e => wx.showToast({ title: e.msg || "保存失败", icon: "none" }));
      }
    });
  },
  goUpload() { wx.navigateTo({ url: "/pages/upload/upload" }); },
  goBenefits() { wx.switchTab({ url: "/pages/benefits/benefits" }); },
  goStructure() { this.setData({ tab: "structure" }); },
  pickStyle(e) {
    const style = e.currentTarget.dataset.style;
    this.setData({ rwStyle: style });
    this.makeRewrite(style, false);
  },
  makeRewrite(style, refresh) {
    if (this.data.rewriting) return;
    this.setData({ rewriting: true, tab: "rewrite" });
    api.rewrite(this.data.taskId, style || this.data.rwStyle, !!refresh).then(r => {
      this.setData({ rewrite: r, rewriting: false });
    }).catch(e => {
      this.setData({ rewriting: false });
      wx.showToast({ title: e.msg || "生成失败", icon: "none" });
    });
  },
  generateRewrite() { this.makeRewrite(this.data.rwStyle, false); },
  refreshRewrite() { this.makeRewrite(this.data.rwStyle, true); },
  copyVersion(e) {
    const i = Number(e.currentTarget.dataset.index);
    const v = ((this.data.rewrite || {}).versions || [])[i];
    if (!v) return;
    wx.setClipboardData({ data: v.text, success: () => wx.showToast({ title: "已复制" }) });
  },
  goPrompter() {
    wx.navigateTo({ url: "/pages/prompter/prompter?taskId=" + this.data.taskId });
  }
});