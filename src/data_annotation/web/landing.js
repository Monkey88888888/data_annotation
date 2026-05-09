const canvas = document.getElementById("heroCanvas");
const ctx = canvas.getContext("2d");
let width = 0;
let height = 0;
let time = 0;

function resize() {
  const ratio = window.devicePixelRatio || 1;
  width = canvas.clientWidth;
  height = canvas.clientHeight;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw() {
  time += 0.006;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#070b12";
  ctx.fillRect(0, 0, width, height);

  drawGrid();
  drawManifold();
  drawSignals();

  requestAnimationFrame(draw);
}

function drawGrid() {
  ctx.save();
  ctx.globalAlpha = 0.34;
  ctx.strokeStyle = "rgba(151, 178, 218, 0.12)";
  ctx.lineWidth = 1;
  const spacing = 42;
  const drift = (time * 80) % spacing;
  for (let x = -spacing; x < width + spacing; x += spacing) {
    ctx.beginPath();
    ctx.moveTo(x + drift, 0);
    ctx.lineTo(x + drift, height);
    ctx.stroke();
  }
  for (let y = -spacing; y < height + spacing; y += spacing) {
    ctx.beginPath();
    ctx.moveTo(0, y + drift * 0.45);
    ctx.lineTo(width, y + drift * 0.45);
    ctx.stroke();
  }
  ctx.restore();
}

function drawManifold() {
  const cx = width * 0.67;
  const cy = height * 0.47;
  ctx.save();
  ctx.translate(cx, cy);
  for (let ring = 0; ring < 6; ring += 1) {
    const rx = Math.max(120, width * 0.34 - ring * 44);
    const ry = Math.max(56, height * 0.22 - ring * 24);
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, Math.sin(time + ring) * 0.08, 0, Math.PI * 2);
    ctx.strokeStyle = ring % 2 === 0 ? "rgba(61, 131, 255, 0.22)" : "rgba(88, 217, 138, 0.2)";
    ctx.lineWidth = 1.4;
    ctx.stroke();
  }

  for (let i = 0; i < 90; i += 1) {
    const angle = i * 0.41 + time * (0.4 + (i % 5) * 0.03);
    const radius = 42 + (i % 17) * 18;
    const x = Math.cos(angle) * radius * 1.8;
    const y = Math.sin(angle * 1.28) * radius * 0.58;
    const isAuthority = i % 4 === 0;
    ctx.fillStyle = isAuthority ? "rgba(88, 217, 138, 0.74)" : "rgba(156, 124, 255, 0.58)";
    ctx.fillRect(x, y, isAuthority ? 4 : 3, isAuthority ? 4 : 3);
  }
  ctx.restore();
}

function drawSignals() {
  const labels = ["authority", "modality", "review", "retrieval", "export"];
  const startX = width * 0.08;
  const startY = height * 0.78;
  const gap = Math.min(180, width * 0.15);

  labels.forEach((label, index) => {
    const x = startX + index * gap;
    const y = startY + Math.sin(time * 3 + index) * 8;
    const active = (Math.floor(time * 24) + index) % 5 < 2;
    ctx.strokeStyle = active ? "rgba(88, 217, 138, 0.62)" : "rgba(151, 178, 218, 0.22)";
    ctx.fillStyle = active ? "rgba(88, 217, 138, 0.92)" : "rgba(151, 178, 218, 0.46)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.roundRect(x, y, 116, 30, 6);
    ctx.stroke();
    ctx.font = "700 11px system-ui";
    ctx.fillText(label.toUpperCase(), x + 12, y + 19);
    if (index < labels.length - 1) {
      ctx.beginPath();
      ctx.moveTo(x + 120, y + 15);
      ctx.lineTo(x + gap - 8, startY + Math.sin(time * 3 + index + 1) * 8 + 15);
      ctx.stroke();
    }
  });
}

if (!CanvasRenderingContext2D.prototype.roundRect) {
  CanvasRenderingContext2D.prototype.roundRect = function roundRect(x, y, w, h, r) {
    this.beginPath();
    this.moveTo(x + r, y);
    this.lineTo(x + w - r, y);
    this.quadraticCurveTo(x + w, y, x + w, y + r);
    this.lineTo(x + w, y + h - r);
    this.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    this.lineTo(x + r, y + h);
    this.quadraticCurveTo(x, y + h, x, y + h - r);
    this.lineTo(x, y + r);
    this.quadraticCurveTo(x, y, x + r, y);
    this.closePath();
    return this;
  };
}

window.addEventListener("resize", resize);
resize();
draw();
