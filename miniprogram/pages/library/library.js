const api = require("../../utils/api");

const PLAT_TEXT = {
  douyin: "抖音", kuaishou: "快手", xiaohongshu: "小红书", bilibili: "B站",
  wechat_article: "公众号", wechat_channels: "视频号", weibo: "微博",
  ixigua: "西瓜", youtube: "YouTube", tiktok: "TikTok", upload: "本地上传"
};

Page({
  data: {
    tasks: [], q: "", platform: "", fav: 0, tag: "", sort: "new", tags: [], total: 0,
    loading: false, hasMore: false, selecting: false, selected: [], selCount: 0,
    filtersOn: false, allSelected: false,
    platforms: [
      { key: "", label: "全部" },
      { key: "douyin", label: "抖音" },
      { key: "xiaohongshu", label: "小红书" },
      { key: "kuaishou", label: "快手" },
      { key: "bilibili", label: "B站" },
      { key: "wechat_article", label: "公众号" },
      { key: "upload", label: "录音/视频" }
    ],
    sorts: [
      { key: "new", label: "最新" },
      { key: "duration", label: "最长" },
      { key: "old", label: "最早" }
    ]
  },
  onShow() { this.reload(); },
  onUnload() { clearTimeout(this.searchTimer); },
  onPullDownRefresh() {
    this.reload(() => wx.stopPullDownRefresh());
  },
  decorate(item) {
    const tags = Array.isArray(item.tags) ? item.tags : [];
    return Object.assign({}, item, {
      platformText: PLAT_TEXT[item.platform] || item.platform || "其他",
      dateText: (item.created_at || "").slice(5, 16),
      tags,
      checked: false
    });
  },
  query(offset) {
    return {
      q: this.data.q.trim(), platform: this.data.platform, fav: this.data.fav,
      tag: this.data.tag, sort: this.data.sort, limit: 20, offset: offset || 0
    };
  },
  syncFilters() {
    const d = this.data;
    this.setData({ filtersOn: !!(d.q || d.platform || d.fav || d.tag) });
  },
  reload(done) {
    this.setData({ loading: true });
    const query = this.query(0);
    Promise.all([api.tasks(query), api.taskTags()])
      .then(([r, t]) => {
        const items = (r.items || []).map(x => this.decorate(x));
        this.setData({
          tasks: items, total: r.total || 0, hasMore: !!r.has_more,
          tags: t.items || [], loading: false, selected: [], selCount: 0, allSelected: false
        });
        this.syncFilters();
        if (done) done();
      })
      .catch(e => {
        this.setData({ loading: false });
        if (done) done();
        wx.showToast({ title: e.msg || "加载失败", icon: "none" });
      });
  },
  loadMore() {
    if (this.data.loading || !this.data.hasMore) return;
    this.setData({ loading: true });
    api.tasks(this.query(this.data.tasks.length))
      .then(r => {
        const more = (r.items || []).map(x => this.decorate(x));
        this.setData({
          tasks: this.data.tasks.concat(more), hasMore: !!r.has_more, loading: false
        });
      })
      .catch(() => this.setData({ loading: false }));
  },
  onSearch(e) {
    this.setData({ q: e.detail.value });
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 400);
  },
  clearSearch() { this.setData({ q: "" }); this.reload(); },
  setPlatform(e) {
    this.setData({ platform: e.currentTarget.dataset.key });
    this.reload();
  },
  toggleFavFilter() { this.setData({ fav: this.data.fav ? 0 : 1 }); this.reload(); },
  setTag(e) {
    const tag = e.currentTarget.dataset.tag;
    this.setData({ tag: this.data.tag === tag ? "" : tag });
    this.reload();
  },
  setSort(e) {
    this.setData({ sort: e.currentTarget.dataset.key });
    this.reload();
  },
  clearFilters() {
    this.setData({ q: "", platform: "", fav: 0, tag: "" });
    this.reload();
  },
  open(e) {
    const id = e.currentTarget.dataset.id;
    if (this.data.selecting) return this.toggleSelect(id);
    wx.navigateTo({ url: "/pages/result/result?taskId=" + id });
  },
  menu(e) {
    const id = e.currentTarget.dataset.id;
    const idx = this.data.tasks.findIndex(x => x.id === id);
    if (idx < 0) return;
    const item = this.data.tasks[idx];
    const actions = ["打开", item.fav ? "取消收藏" : "收藏", "加标签", "重命名", "删除"];
    wx.showActionSheet({
      itemList: actions,
      success: r => {
        if (r.tapIndex === 0) return wx.navigateTo({ url: "/pages/result/result?taskId=" + id });
        if (r.tapIndex === 1) return this.setFav(idx, item.fav ? 0 : 1);
        if (r.tapIndex === 2) return this.editTags(idx);
        if (r.tapIndex === 3) return this.rename(idx);
        if (r.tapIndex === 4) return this.remove(idx);
      }
    });
  },
  setFav(idx, fav) {
    const item = this.data.tasks[idx];
    api.patchTask(item.id, { fav })
      .then(() => {
        this.setData({ ["tasks[" + idx + "].fav"]: fav });
        wx.showToast({ title: fav ? "已收藏" : "已取消" });
      })
      .catch(err => wx.showToast({ title: err.msg || "操作失败", icon: "none" }));
  },
  star(e) {
    const id = e.currentTarget.dataset.id;
    const idx = this.data.tasks.findIndex(x => x.id === id);
    if (idx < 0) return;
    this.setFav(idx, this.data.tasks[idx].fav ? 0 : 1);
  },
  editTags(idx) {
    const item = this.data.tasks[idx];
    wx.showModal({
      title: "标签",
      editable: true,
      placeholderText: "空格或逗号分隔，最多 8 个",
      content: (item.tags || []).join(" "),
      success: r => {
        if (!r.confirm) return;
        const tags = String(r.content || "").split(/[\s,，、]+/).filter(Boolean).slice(0, 8);
        api.patchTask(item.id, { tags })
          .then(res => {
            this.setData({ ["tasks[" + idx + "].tags"]: res.tags || [] });
            wx.showToast({ title: "标签已保存" });
            this.reload();
          })
          .catch(err => wx.showToast({ title: err.msg || "保存失败", icon: "none" }));
      }
    });
  },
  rename(idx) {
    const item = this.data.tasks[idx];
    wx.showModal({
      title: "重命名",
      editable: true,
      placeholderText: "给这条稿子起个名字",
      content: item.title || "",
      success: r => {
        if (!r.confirm) return;
        const title = String(r.content || "").trim();
        if (!title) return wx.showToast({ title: "名字不能为空", icon: "none" });
        api.patchTask(item.id, { title })
          .then(res => {
            this.setData({ ["tasks[" + idx + "].title"]: res.title });
            wx.showToast({ title: "已改名" });
          })
          .catch(err => wx.showToast({ title: err.msg || "改名失败", icon: "none" }));
      }
    });
  },
  remove(idx) {
    const item = this.data.tasks[idx];
    wx.showModal({
      title: "删除这条稿子？",
      content: "删除后不再出现在素材库，已用掉的次数不退回。",
      confirmText: "删除",
      confirmColor: "#D93025",
      success: r => {
        if (!r.confirm) return;
        api.removeTask(item.id)
          .then(() => {
            const tasks = this.data.tasks.filter(x => x.id !== item.id);
            const selected = this.data.selected.filter(x => x !== item.id);
            this.setData({ tasks, total: Math.max(0, this.data.total - 1), selected, selCount: selected.length });
            wx.showToast({ title: "已删除" });
          })
          .catch(err => wx.showToast({ title: err.msg || "删除失败", icon: "none" }));
      }
    });
  },
  toggleSelectMode() {
    if (this.data.selecting) {
      return this.setData({
        selecting: false, selected: [], selCount: 0, allSelected: false,
        tasks: this.data.tasks.map(x => Object.assign({}, x, { checked: false }))
      });
    }
    this.setData({ selecting: true });
  },
  toggleSelect(id) {
    const tasks = this.data.tasks.map(x => x.id === id ? Object.assign({}, x, { checked: !x.checked }) : x);
    const selected = tasks.filter(x => x.checked).map(x => x.id);
    this.setData({
      tasks, selected, selCount: selected.length,
      allSelected: selected.length > 0 && selected.length === tasks.filter(x => x.status === "done").length
    });
  },
  selectAll() {
    const doneTasks = this.data.tasks.filter(x => x.status === "done");
    const all = this.data.allSelected;
    const tasks = this.data.tasks.map(x => Object.assign({}, x, { checked: !all && x.status === "done" }));
    const selected = all ? [] : doneTasks.map(x => x.id);
    this.setData({ tasks, selected, selCount: selected.length, allSelected: !all });
  },
  exportSelected(e) {
    const fmt = e.currentTarget.dataset.fmt;
    const ids = this.data.selected || [];
    if (!ids.length) return wx.showToast({ title: "先勾选稿子", icon: "none" });
    const zip = fmt === "zip";
    const real = zip ? "docx" : fmt;
    wx.showLoading({ title: zip ? "正在打包" : "正在导出", mask: true });
    api.batchExport(ids, real, zip)
      .then(p => {
        wx.hideLoading();
        if (zip) return api.shareFile(p, "文案合集-" + ids.length + "条.zip");
        return api.openDoc(p, real);
      })
      .then(() => {})
      .catch(err => {
        wx.hideLoading();
        wx.showToast({ title: err.msg || "导出失败", icon: "none" });
      });
  }
});