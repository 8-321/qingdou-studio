const api = require("../../utils/api");

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
}

Page({
  data: {
    uploading: false,
    recording: false,
    seconds: 0,
    timeText: "00:00",
    progress: 0
  },
  onLoad() {
    this.rec = wx.getRecorderManager();
    this.rec.onStop(res => {
      this.clearTimer();
      this.setData({ recording: false });
      if (!this.leaving && res && res.tempFilePath) this.upload(res.tempFilePath);
    });
    this.rec.onError(err => {
      this.clearTimer();
      this.setData({ recording: false });
      wx.showToast({ title: (err && err.errMsg) || "录音失败", icon: "none" });
    });
  },
  onUnload() {
    this.leaving = true;
    this.clearTimer();
    if (this.data.recording) this.rec.stop();
  },
  clearTimer() {
    clearInterval(this.timer);
    this.timer = null;
  },
  startRec() {
    wx.authorize({
      scope: "scope.record",
      success: () => this.beginRec(),
      fail: () => {
        wx.showModal({
          title: "需要麦克风权限",
          content: "去设置里打开「麦克风」后就能直接录音提取。",
          confirmText: "去设置",
          success: r => { if (r.confirm) wx.openSetting(); }
        });
      }
    });
  },
  beginRec() {
    this.setData({ seconds: 0, timeText: "00:00", recording: true });
    this.rec.start({
      duration: 600000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: "mp3"
    });
    this.clearTimer();
    this.timer = setInterval(() => {
      const n = this.data.seconds + 1;
      this.setData({ seconds: n, timeText: fmt(n) });
      if (n >= 600) this.stopRec();
    }, 1000);
  },
  stopRec() {
    if (!this.data.recording) return;
    this.rec.stop();
  },
  pickVideo() {
    if (this.data.recording) return wx.showToast({ title: "先停止录音", icon: "none" });
    wx.chooseMedia({
      count: 1, mediaType: ["video"], sourceType: ["album", "camera"], maxDuration: 600,
      success: res => this.upload(res.tempFiles[0].tempFilePath)
    });
  },
  pickFile() {
    if (this.data.recording) return wx.showToast({ title: "先停止录音", icon: "none" });
    wx.chooseMessageFile({
      count: 1, type: "file",
      success: res => this.upload(res.tempFiles[0].path)
    });
  },
  upload(path) {
    if (!path || this.data.uploading) return;
    this.setData({ uploading: true, progress: 0 });
    wx.showLoading({ title: "上传中" });
    api.upload(path, p => this.setData({ progress: p })).then(r => {
      wx.hideLoading();
      this.setData({ uploading: false });
      wx.redirectTo({ url: "/pages/result/result?taskId=" + r.task_id });
    }).catch(e => {
      wx.hideLoading();
      this.setData({ uploading: false });
      wx.showToast({ title: e.msg || "上传失败", icon: "none" });
    });
  }
});
