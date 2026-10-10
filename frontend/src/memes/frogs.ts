export type MemeKind = 'profit' | 'loss' | 'entry' | 'neutral';

export function frogImage(kind: MemeKind, variant = 0): string {
  variant %= kind === 'entry' ? 2 : 3;
  const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 480;
  const c = canvas.getContext('2d'); if (!c) return '';
  c.lineCap = 'round'; c.lineJoin = 'round';
  const oval = (x: number, y: number, rx: number, ry: number, fill: string) => {
    c.beginPath(); c.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); c.fillStyle = fill; c.fill();
    c.lineWidth = 7; c.strokeStyle = '#18362a'; c.stroke();
  };
  oval(243, 429, 166, 25, '#253e35');
  oval(237, 328, 134, 91, ['#729a65', '#82a76c', '#6d9c7b'][variant % 3]);
  oval(167, 223, 58, 81, '#91b976'); oval(314, 211, 59, 79, '#91b976');
  oval(244, 284, 160, 106, '#91b976');
  oval(169, 217, 37, 48, '#f3e8cd'); oval(316, 209, 37, 48, '#f3e8cd');
  oval(177 + variant * 3, kind === 'loss' ? 231 : 215, 10, 17, '#19382b');
  oval(307 + variant * 3, kind === 'loss' ? 222 : 205, 10, 17, '#19382b');
  c.strokeStyle = '#244432'; c.lineWidth = 8; c.beginPath();
  c.moveTo(158, kind === 'loss' ? 326 : 298);
  c.quadraticCurveTo(246, kind === 'loss' ? 286 : kind === 'neutral' ? 309 : 366, 329, 302); c.stroke();
  oval(147, 376, 42, 24, '#91b976'); oval(337, 375, 43, 24, '#91b976');
  if (kind === 'loss') {
    c.fillStyle = '#a1cce1'; c.beginPath(); c.moveTo(332, 255); c.quadraticCurveTo(304, 292, 334, 294); c.quadraticCurveTo(354, 293, 332, 255); c.fill();
  } else if (kind === 'profit' && variant === 1) {
    c.fillStyle = '#263938'; c.fillRect(126, 194, 82, 42); c.fillRect(277, 184, 80, 42); c.fillRect(207, 204, 72, 9);
  } else if (kind === 'entry') {
    c.fillStyle = '#e8bb72'; c.beginPath(); c.moveTo(205, 145); c.lineTo(254, 98); c.lineTo(294, 148); c.closePath(); c.fill();
  }
  return canvas.toDataURL('image/png');
}