import { useCallback, useEffect, useRef, useState } from 'react';
import { api, BASE, fileToJpegB64, fmt, img, left, tok, toLocalInput } from './api.js';
import { Post } from './ui.jsx';

export function usePoll(fn, ms, deps = []) {
  useEffect(() => { fn(); const t = ms && setInterval(fn, ms); return () => t && clearInterval(t); }, deps); // eslint-disable-line
}
const safe = f => async (...a) => { try { await f(...a); } catch (e) { alert(e.message); } };
const quiet = f => async (...a) => { try { await f(...a); } catch { /* background refresh: keep what is on screen */ } };

export function Auth({ onAuth }) {
  const [mode, setMode] = useState('login'), [err, setErr] = useState(''), [code, setCode] = useState(null), [session, setSession] = useState(null);
  const [f, setF] = useState({ name: '', username: '', phone: '', identifier: '', password: '', code: '' });
  const set = k => e => setF({ ...f, [k]: e.target.value });
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const submit = async () => {
    try {
      setErr('');
      if (mode === 'login') { const r = await api('/auth/login', { method: 'POST', body: { identifier: f.identifier, password: f.password } }); tok.set(r.token); onAuth(r.user); }
      else if (mode === 'signup') { const r = await api('/auth/register', { method: 'POST', body: { name: f.name, username: f.username || null, phone: f.phone || null, password: f.password, timezone: tz } }); tok.set(r.token); setSession(r.user); setCode(r.recovery_code); }
      else { const r = await api('/auth/reset', { method: 'POST', body: { identifier: f.identifier, recovery_code: f.code, password: f.password } }); setCode(r.recovery_code); setSession(null); }
    } catch (e) { setErr(e.message); }
  };
  if (code) return (<>
    <div className="hw" style={{ fontSize: 32, margin: '0 0 6px' }}>Save your recovery code</div>
    <div className="mu" style={{ margin: '0 0 12px' }}>If you forget your password, this code is the only way back in. Screenshot it or write it down. It is shown once.</div>
    <div className="note"><div className="tape" /><div className="hw" style={{ fontSize: 44, color: 'var(--ru)', textAlign: 'center', letterSpacing: 2 }}>{code}</div></div>
    <button className="btn r" onClick={() => { if (session) onAuth(session); else { setCode(null); setMode('login'); } }}>I saved it</button>
  </>);
  const field = (k, ph, type = 'text') => <input style={{ marginTop: 8 }} type={type} placeholder={ph} value={f[k]} onChange={set(k)} />;
  return (<>
    <div className="hw" style={{ fontSize: 40 }}>Study Pulse</div>
    <div className="mu" style={{ margin: '0 0 14px' }}>Find classmates stuck on the same topic.</div>
    <div className="row" style={{ margin: '0 0 10px' }}>{[['login', 'Sign in'], ['signup', 'Create account'], ['recover', 'Forgot password']].map(([k, l]) => <button key={k} className={'chip ' + (mode === k ? 'on' : '')} onClick={() => { setMode(k); setErr(''); }}>{l}</button>)}</div>
    <div className="note">
      {mode === 'signup' && <>{field('name', 'Your name (shown to classmates)')}{field('username', 'Username (or use a phone number)')}{field('phone', 'Phone with country code, e.g. +234 801 234 5678 (optional)')}</>}
      {mode !== 'signup' && field('identifier', 'Username or phone number')}
      {mode === 'recover' && field('code', 'Recovery code (XXXX-XXXX)')}
      {field('password', mode === 'recover' ? 'New password (6+ characters)' : 'Password (6+ characters)', 'password')}
      <button className="btn r" style={{ marginTop: 12 }} onClick={submit}>{mode === 'login' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Reset password'}</button>
    </div>
    {mode === 'signup' && <div className="mu">Your phone number and username are private. Classmates only ever see your name, or your Anon name when you post anonymously.</div>}
    <div className="mu" style={{ color: 'var(--ru)' }}>{err}</div>
  </>);
}

export function JoinClass({ onDone, onCancel }) {
  const [code, setCode] = useState(''), [name, setName] = useState(''), [subject, setSubject] = useState('');
  return (<>
    {onCancel && <button className="btn" onClick={onCancel} style={{ margin: '0 0 12px' }}>‹ Back</button>}
    <div className="hw" style={{ fontSize: 32, margin: '0 0 10px' }}>Join your class</div>
    <div className="note"><div className="tape" />
      <input placeholder="Class code, e.g. A1B2C3" value={code} onChange={e => setCode(e.target.value)} />
      <button className="btn r" style={{ marginTop: 10 }} onClick={safe(async () => onDone(await api('/classes/join', { method: 'POST', body: { code } })))}>Join</button>
    </div>
    <div className="hw" style={{ fontSize: 22, margin: '0 0 6px' }}>Or start one</div>
    <div className="note">
      <input placeholder="Class name, e.g. Physics, Grade 11" value={name} onChange={e => setName(e.target.value)} />
      <input style={{ marginTop: 8 }} placeholder="Subject (optional)" value={subject} onChange={e => setSubject(e.target.value)} />
      <button className="btn" style={{ marginTop: 10 }} onClick={safe(async () => onDone(await api('/classes', { method: 'POST', body: { name, subject: subject || null } })))}>Create class</button>
    </div>
  </>);
}

export function Home({ cid, go }) {
  const [posts, setPosts] = useState([]), [topics, setTopics] = useState([]), [f, setF] = useState('all'), [t, setT] = useState(null);
  const load = useCallback(quiet(async () => {
    const [p, tp] = await Promise.all([api(`/classes/${cid}/posts`), api(`/classes/${cid}/topics`)]);
    setPosts(p); setTopics(tp.slice(0, 6));
  }), [cid]);
  usePoll(load, 15000, [cid]);
  const meToo = safe(async id => { await api(`/posts/${id}/me-too`, { method: 'POST' }); await load(); });
  const message = safe(async id => { const c = await api('/conversations', { method: 'POST', body: { post_id: id } }); go('chat', { id: c.id }); });
  let shown = posts.filter(p => (f === 'all' || p.type === f) && (!t || p.topic === t));
  if (f === 'radar') shown = [...shown].sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  return (<>
    <div className="hw" style={{ fontSize: 20, margin: '8px 0 6px' }}>Stuck on this right now</div>
    <div className="row" style={{ gap: 10, overflowX: 'auto', margin: '0 0 12px' }}>
      {topics.map(x => <div key={x.topic} className="hotw" onClick={() => setT(t === x.topic ? null : x.topic)}><div className={'hot hw ' + (t && t !== x.topic ? 'off' : '')}>{x.stuck_count}</div>{x.topic}</div>)}
      {!topics.length && <span className="mu">No struggles posted yet.</span>}
    </div>
    <div className="row" style={{ margin: '0 0 14px' }}>{[['all', 'All'], ['struggle', 'Struggles'], ['radar', 'Deadlines']].map(([k, l]) => <button key={k} className={'chip ' + (f === k ? 'on' : '')} onClick={() => setF(k)}>{l}</button>)}</div>
    {shown.map(p => <Post key={p.id} p={p} onOpen={id => go('detail', { id })} onMeToo={meToo} onMessage={message} />)}
    {!shown.length && <div className="mu">Nothing here yet. Tap + to post.</div>}
  </>);
}

export function Detail({ id, me, go, back }) {
  const [p, setP] = useState(null), [cm, setCm] = useState([]), [text, setText] = useState(''), [anon, setAnon] = useState(false);
  const load = useCallback(async () => {
    try { setP(await api(`/posts/${id}`)); setCm(await api(`/posts/${id}/comments`)); }
    catch (e) { if (/not found/i.test(e.message)) back(); }   // note was deleted
  }, [id]);
  usePoll(load, 0, [id]);
  const dm = safe(async cid => { const c = await api('/conversations', { method: 'POST', body: { post_id: id, comment_id: cid || null } }); go('chat', { id: c.id }); });
  if (!p) return null;
  return (<>
    <button className="btn" onClick={back} style={{ margin: '0 0 12px' }}>‹ Back</button>
    <Post p={p} detail onMeToo={safe(async () => { await api(`/posts/${id}/me-too`, { method: 'POST' }); load(); })} onMessage={() => dm()} />
    <div className="row" style={{ margin: '-6px 0 12px' }}>
      <button className="btn" onClick={safe(async () => { await api(`/posts/${id}/report`, { method: 'POST', body: { reason: 'reported' } }); alert('Reported. Thank you.'); })}>Report</button>
      {p.can_delete && <button className="btn" onClick={safe(async () => { if (confirm(p.is_mine ? 'Delete this note?' : 'Remove this note from the class?')) { await api(`/posts/${id}`, { method: 'DELETE' }); back(); } })}>Delete</button>}
    </div>
    <div className="hw" style={{ fontSize: 22, margin: '0 0 8px' }}>Comments</div>
    {cm.map(c => <div key={c.id} className="row sp" style={{ margin: '0 0 10px', alignItems: 'flex-start' }}>
      <div><b>{c.display_name}</b>{c.is_anonymous && <span className="mu"> anonymous</span>}<div>{c.content}</div></div>
      {!c.is_mine && <button className="btn" onClick={() => dm(c.id)}>Message</button>}
    </div>)}
    {!cm.length && <div className="mu" style={{ margin: '0 0 10px' }}>Be the first to help.</div>}
    <div className="row"><input placeholder="Write a comment" value={text} onChange={e => setText(e.target.value)} />
      <button className="btn r" onClick={safe(async () => { if (!text.trim()) return; await api(`/posts/${id}/comments`, { method: 'POST', body: { content: text, is_anonymous: anon } }); setText(''); load(); })}>Send</button></div>
    <label className="mu row" style={{ marginTop: 8 }}><input type="checkbox" style={{ width: 'auto' }} checked={anon} onChange={e => setAnon(e.target.checked)} /> Comment anonymously (as {me.anon})</label>
  </>);
}

export function Compose({ cls, done }) {
  const [pic, setPic] = useState(null), [text, setText] = useState(''), [topic, setTopic] = useState(''), [anon, setAnon] = useState(true), [draft, setDraft] = useState(null), [busy, setBusy] = useState(false), [rt, setRt] = useState(''), [listen, setListen] = useState(false);
  const file = useRef(), attach = useRef();
  const upload = safe(async e => { const f = e.target.files[0]; e.target.value = ''; if (!f) return; const { data } = await fileToJpegB64(f); const r = await api('/uploads', { method: 'POST', body: { image_base64: data } }); setPic(r.url); });
  const read = safe(async (body) => {
    setBusy(true);
    try { const r = await api('/radar/parse', { method: 'POST', body: { ...body, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } }); setDraft({ title: r.title || '', due: toLocalInput(r.due_date), warn: !!(r.needs_clarification || !r.due_date) }); }
    finally { setBusy(false); }
  });
  const rec = useRef();
  const voice = safe(async () => {
    if (listen) { rec.current.stop(); return; }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream), chunks = [];
    mr.ondataavailable = e => chunks.push(e.data);
    mr.onstop = safe(async () => {
      stream.getTracks().forEach(t => t.stop()); setListen(false);
      const blob = new Blob(chunks, { type: mr.mimeType });
      const b64 = await new Promise(r => { const x = new FileReader(); x.onload = () => r(x.result.split(',')[1]); x.readAsDataURL(blob); });
      setBusy(true);
      try { const t = await api('/radar/transcribe', { method: 'POST', body: { audio_base64: b64, media_type: blob.type } }); setRt(t.text); await read({ text: t.text }); } finally { setBusy(false); }
    });
    rec.current = mr; mr.start(); setListen(true);
  });
  const photo = safe(async e => { const f = e.target.files[0]; e.target.value = ''; if (!f) return; const { data, type } = await fileToJpegB64(f); await read({ image_base64: data, media_type: type }); });
  const postR = safe(async () => { if (!draft.title.trim() || !draft.due) return alert('Add a title and due date'); await api(`/classes/${cls.id}/posts`, { method: 'POST', body: { type: 'radar', radar_title: draft.title, due_at: new Date(draft.due).toISOString() } }); done(); });
  const saveR = safe(async () => { if (!draft.title.trim() || !draft.due) return alert('Add a title and due date'); await api(`/classes/${cls.id}/deadlines`, { method: 'POST', body: { title: draft.title, due_at: new Date(draft.due).toISOString() } }); done('radar'); });
  return (<>
    <div className="row sp" style={{ margin: '0 0 10px' }}><h2 className="hw" style={{ fontSize: 26 }}>New note</h2><span className="chip">{cls.name} only</span></div>
    <div className="note"><textarea placeholder="What are you stuck on?" value={text} onChange={e => setText(e.target.value)} /><input style={{ marginTop: 8 }} placeholder="Topic (e.g. Moment of inertia)" value={topic} onChange={e => setTopic(e.target.value)} /></div>
    <div className="row sp" style={{ background: 'var(--rt)', border: '1px solid var(--ru)', borderRadius: 12, padding: '10px 12px', margin: '0 0 14px' }}>
      <div><div className="hw" style={{ fontSize: 20, lineHeight: 1.1 }}>Post as {anon ? cls.my_anon_name : 'yourself'}</div><div className="mu">{anon ? 'Name and photo stay hidden' : 'Your name will be visible to the class'}</div></div>
      <button className={'tog ' + (anon ? 'on' : '')} aria-label="Post anonymously" onClick={() => setAnon(!anon)} />
    </div>
    {pic && <img src={img(pic)} alt="Preview" style={{ width: 90, borderRadius: 8, margin: '0 0 10px', display: 'block' }} />}
    <input ref={attach} type="file" accept="image/*" hidden onChange={upload} />
    <div className="row" style={{ margin: '0 0 20px' }}><button className="btn" onClick={() => attach.current.click()}>{pic ? 'Change picture' : 'Add picture'}</button>
    <button className="btn r" onClick={safe(async () => { if (!text.trim()) return; await api(`/classes/${cls.id}/posts`, { method: 'POST', body: { type: 'struggle', content: text, topic: topic.trim() || 'General', is_anonymous: anon, photo_url: pic } }); done(); })}>Post to class</button></div>
    <div className="hw" style={{ fontSize: 20, color: 'var(--ru)', margin: '0 0 6px' }}>Or let Radar do the typing</div>
    <div className="row" style={{ margin: '0 0 8px' }}><button className="tile" onClick={voice}>{listen ? 'Tap to stop' : 'Voice note'}</button><button className="tile" onClick={() => file.current.click()}>Photo of task</button><button className="tile" onClick={() => document.getElementById('rt').focus()}>Rough text</button></div>
    <input ref={file} type="file" accept="image/*" hidden onChange={photo} />
    <div className="row"><input id="rt" placeholder="e.g. physics lab report due friday 5pm" value={rt} onChange={e => setRt(e.target.value)} /><button className="btn" onClick={() => rt.trim() && read({ text: rt })}>Read</button></div>
    {busy && <div className="mu" style={{ marginTop: 8 }}>Radar is reading...</div>}
    {draft && <div className="note" style={{ marginTop: 18, transform: 'rotate(.6deg)' }}><div className="tape" /><div className="mu">Radar read this</div>
      <input style={{ margin: '4px 0 8px' }} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} />
      <input type="datetime-local" style={draft.warn ? { borderColor: 'var(--ru)' } : {}} value={draft.due} onChange={e => setDraft({ ...draft, due: e.target.value })} />
      {draft.warn && <div className="mu" style={{ color: 'var(--ru)' }}>Check the date before posting.</div>}
      <div className="row" style={{ marginTop: 10 }}><button className="btn r" onClick={postR}>Post to class</button><button className="btn" onClick={saveR}>Save privately</button></div></div>}
  </>);
}

export function RadarTab({ cid }) {
  const [cls, setCls] = useState([]), [mine, setMine] = useState([]);
  const load = quiet(async () => { setCls(await api(`/classes/${cid}/posts?type=radar`)); setMine(await api(`/classes/${cid}/deadlines`)); });
  usePoll(load, 0, [cid]);
  const li = (k, t, d, x, del) => <div key={k} className="row sp" style={{ margin: '0 0 10px' }}><div><b>{t}</b><div className="mu">{fmt(d)} {x}</div></div>
    <div style={{ textAlign: 'right' }}><span className="hw" style={{ fontSize: 20, color: new Date(d) - Date.now() < 864e5 ? 'var(--ru)' : 'var(--ink)' }}>{left(d)}</span>{del && <div><button className="mu" style={{ border: 0, background: 'none' }} onClick={del}>remove</button></div>}</div></div>;
  return (<>
    <h2 className="hw" style={{ fontSize: 28, margin: '0 0 10px' }}>Radar</h2>
    <div className="hw" style={{ fontSize: 20, color: 'var(--ru)' }}>Class deadlines</div>
    <div className="note" style={{ marginTop: 8 }}>{cls.map(p => li('c' + p.id, p.radar_title, p.due_at, '· ' + p.display_name)) }{!cls.length && <span className="mu">None yet.</span>}</div>
    <div className="hw" style={{ fontSize: 20, color: 'var(--ru)' }}>My private deadlines</div>
    <div className="note" style={{ marginTop: 8 }}>{mine.map(d => li('m' + d.id, d.title, d.due_at, '', safe(async () => { await api(`/deadlines/${d.id}`, { method: 'DELETE' }); load(); })))}{!mine.length && <span className="mu">Nothing saved yet.</span>}</div>
  </>);
}

export function Inbox({ go }) {
  const [cs, setCs] = useState([]);
  usePoll(quiet(async () => setCs(await api('/conversations'))), 10000);
  return (<>
    <h2 className="hw" style={{ fontSize: 28, margin: '0 0 10px' }}>Inbox</h2>
    {cs.map(c => <div key={c.id} className="note" onClick={() => go('chat', { id: c.id })}><b>{c.other_label}</b><div className="mu">About: {c.topic}</div></div>)}
    {!cs.length && <div className="mu">Tap Message on a note to start a private chat.</div>}
  </>);
}

export function Chat({ id, back }) {
  const [d, setD] = useState(null), [t, setT] = useState('');
  const load = useCallback(async () => {
    try { setD(await api(`/conversations/${id}/messages`)); } catch (e) { if (/not found/i.test(e.message)) back(); }
  }, [id]);
  usePoll(load, 15000, [id]);   // slow fallback; live updates arrive over the websocket
  useEffect(() => {
    const base = (BASE || window.location.origin).replace(/^http/, 'ws');
    const ws = new WebSocket(`${base}/ws/conversations/${id}?token=${tok.get()}`);
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.type === 'reveal') { load(); return; }   // the other person revealed their name
      setD(p => p && !p.messages.some(x => x.id === m.id) ? { ...p, messages: [...p.messages, m] } : p);
    };
    return () => ws.close();
  }, [id]);
  if (!d) return null;
  const c = d.conversation;
  return (<>
    <button className="btn" onClick={back} style={{ margin: '0 0 10px' }}>‹ Inbox</button>
    <div className="row" style={{ margin: '0 0 8px' }}>
      <div className={'av hw ' + (c.other_hidden ? '' : 'real')}>{c.other_hidden ? '?' : c.other_label.slice(0, 2)}</div>
      <div><div className="hw" style={{ fontSize: 22, lineHeight: 1 }}>{c.other_label}</div><div className="mu">About: {c.topic}</div></div>
    </div>
    <div className="pulse mu" style={{ textAlign: 'center' }}>{c.other_hidden || c.me_anon ? 'Names stay hidden until someone reveals' : 'Private chat'}</div>
    {d.messages.map(m => <div key={m.id} className={'b ' + (m.is_mine ? 'mine' : 'them')}>{m.content}</div>)}
    {c.me_anon && <div className="row sp" style={{ margin: '6px 0 10px' }}><button className="btn" disabled={c.me_revealed} onClick={safe(async () => { await api(`/conversations/${id}/reveal`, { method: 'POST' }); load(); })}>{c.me_revealed ? 'Your name is revealed' : 'Reveal my name'}</button><span className="mu">Only you decide this</span></div>}
    <form className="row" onSubmit={safe(async e => { e.preventDefault(); if (!t.trim()) return; await api(`/conversations/${id}/messages`, { method: 'POST', body: { content: t } }); setT(''); load(); })}>
      <input placeholder="Write a message" value={t} onChange={e => setT(e.target.value)} /><button className="btn r">Send</button>
    </form>
  </>);
}

export function ClassTab({ cls, onJoinAnother, onSignOut }) {
  return (<>
    <h2 className="hw" style={{ fontSize: 28, margin: '0 0 10px' }}>Class</h2>
    <div className="note"><div className="tape" /><b>{cls.name}</b><div className="mu">Share this code so classmates can join</div><div className="hw" style={{ fontSize: 40, color: 'var(--ru)' }}>{cls.code}</div><div className="mu">{cls.member_count} in this class</div></div>
    {cls.is_owner && <Moderation cid={cls.id} />}
    <div className="note"><b>Your name in this class when anonymous</b><div className="hw" style={{ fontSize: 24 }}>{cls.my_anon_name}</div></div>
    <div className="row"><button className="btn" onClick={onJoinAnother}>Join another class</button><button className="btn" onClick={onSignOut}>Sign out</button></div>
  </>);
}

function Moderation({ cid }) {
  const [rs, setRs] = useState([]);
  const load = safe(async () => setRs(await api(`/classes/${cid}/reports`)));
  usePoll(load, 0, [cid]);
  return (<div className="note"><b>Moderation</b>
    {!rs.length && <div className="mu">No reported notes.</div>}
    {rs.map(r => <div key={r.post_id} style={{ margin: '10px 0' }}>
      <div className="mu">{r.display_name} · {r.report_count} report(s){r.reasons.length ? ' · ' + r.reasons.join(', ') : ''}</div><div>{r.preview}</div>
      <div className="row" style={{ marginTop: 6 }}>
        <button className="btn r" onClick={safe(async () => { await api(`/posts/${r.post_id}`, { method: 'DELETE' }); load(); })}>Remove note</button>
        <button className="btn" onClick={safe(async () => { await api(`/classes/${cid}/reports/${r.post_id}`, { method: 'DELETE' }); load(); })}>Dismiss</button></div></div>)}
  </div>);
}
