export const BASE = import.meta.env.VITE_API_URL || '';
export const tok = { get: () => localStorage.getItem('sp_token'), set: t => (t ? localStorage.setItem('sp_token', t) : localStorage.removeItem('sp_token')) };

export async function api(path, { method = 'GET', body } = {}) {
  const r = await fetch(BASE + '/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(tok.get() ? { Authorization: 'Bearer ' + tok.get() } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 204) return null;
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && tok.get() && !path.startsWith('/auth/')) { tok.set(null); window.location.reload(); }   // expired session
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || 'Something went wrong').replace(/^Value error, /, ''));
  return j;
}

export const left = iso => { const h = (new Date(iso) - Date.now()) / 36e5; return h < 0 ? 'overdue' : h < 24 ? (h < 1 ? 'under 1h' : Math.ceil(h) + 'h left') : Math.ceil(h / 24) + ' days left'; };
// Shrinks a camera photo in the browser (max 1280px JPEG) so uploads stay small and fast.
export async function fileToJpegB64(file, max = 1280) {
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas');
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    return { data: c.toDataURL('image/jpeg', 0.85).split(',')[1], type: 'image/jpeg' };
  } catch {
    return new Promise(r => { const x = new FileReader(); x.onload = () => r({ data: x.result.split(',')[1], type: file.type }); x.readAsDataURL(file); });
  }
}
export const img = u => (u && u.startsWith('http') ? u : BASE + u);
export const ago = iso => { const m = (Date.now() - new Date(iso)) / 6e4; return m < 1 ? 'now' : m < 60 ? Math.floor(m) + 'm' : m < 1440 ? Math.floor(m / 60) + 'h' : Math.floor(m / 1440) + 'd'; };
export const fmt = iso => new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
export const toLocalInput = iso => iso ? new Date(new Date(iso) - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 16) : '';
