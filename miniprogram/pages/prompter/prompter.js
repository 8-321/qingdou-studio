Page({
  data: {
    title: "",
    paras: [],
    top: 0,
    playing: false,
    speed: 1,
    fontSize: 52
  },
  onLoad(q) {
    this.taskId = q.taskId;
    const api = require("../../utils/api");
    api.result(q.taskId).then(r => {
      const paras = (r.segments || []).filter(s => s.text).map((s, i) => ({ i, text: s.text }));
      this.setData({ title: r.title || "提词器", paras });
      wx.setNavigationBarTitle({ title: "提词器" });
    }).catch(e => wx.showToast({ title: e.msg || "读取失败", icon: "none" }));
  },
  onUnload() { this.pause(); },
  toggle() { this.data.playing ? this.pause() : this.play(); },
  play() {
    if (this.data.playing) return;
    this.setData({ playing: true });
    this.timer = setInterval(() => {
      this.setData({ top: this.data.top + this.data.speed * 2 });
    }, 80);
  },
  pause() {
    clearInterval(this.timer);
    this.setData({ playing: false });
  },
  reset() { this.setData({ top: 0 }); },
  speed(e) {
    const delta = Number(e.currentTarget.dataset.delta);
    this.setData({ speed: Math.max(1, Math.min(6, this.data.speed + delta)) });
  },
  font(e) {
    const delta = Number(e.currentTarget.dataset.delta);
    this.setData({ fontSize: Math.max(36, Math.min(80, this.data.fontSize + delta)) });
  }
});
