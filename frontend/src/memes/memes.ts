import { api, apiBlob } from '../api';
import { frogImage, type MemeKind } from './frogs';

export function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => image.naturalWidth * image.naturalHeight <= 24000000 ? resolve(image) : reject(new Error('Image dimensions exceed 24 megapixels.'));
    image.onerror = () => reject(new Error('Could not decode image.'));
    image.src = url;
  });
}

export async function pickMeme(token: string, kind: MemeKind, signal: AbortSignal, variant: number): Promise<{ image: HTMLImageElement; fallback: boolean }> {
  const fallback = async (failed: boolean) => ({ image: await loadImage(frogImage(kind, variant)), fallback: failed });
  if (kind === 'neutral') return fallback(false);
  try {
    const files = await api<Record<string, string[]>>(token, '/memes', { signal });
    const options = files[kind];
    if (!options?.length) return fallback(false);
    const name = options[Math.floor(Math.random() * options.length)];
    const blob = await apiBlob(token, `/memes/${kind}/${encodeURIComponent(name)}`, signal);
    const url = URL.createObjectURL(blob);
    try { return { image: await loadImage(url), fallback: false }; }
    finally { URL.revokeObjectURL(url); }
  } catch (error) { if (signal.aborted) throw error; return fallback(true); }
}