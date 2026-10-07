export function promoPlayer() {
  return {
    scene: 0,
    playing: true,
    progress: 0,
    timer: null,
    sceneDurations: [6000, 9000, 8000, 7000],
    labels: ['Meet Lumen', 'Every plan, one tab', 'Docs that update themselves', 'Launching Spring 2026'],
    init() {
      this.tick();
    },
    tick() {
      const start = performance.now();
      const duration = this.sceneDurations[this.scene];
      const step = (now) => {
        if (!this.playing) return;
        const elapsed = now - start;
        this.progress = Math.min(100, (elapsed / duration) * 100);
        if (elapsed >= duration) {
          this.scene = (this.scene + 1) % 4;
          this.progress = 0;
          this.tick();
        } else {
          this.timer = requestAnimationFrame(step);
        }
      };
      this.timer = requestAnimationFrame(step);
    },
    toggle() {
      this.playing = !this.playing;
      if (this.playing) this.tick();
      else cancelAnimationFrame(this.timer);
    },
    restart() {
      cancelAnimationFrame(this.timer);
      this.scene = 0;
      this.progress = 0;
      this.playing = true;
      this.tick();
    },
    sceneLabel() { return this.labels[this.scene]; }
  };
}
