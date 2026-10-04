import { ago, img, left } from './api.js';

export const Logo = () => (
  <div>
    <div className="hw" style={{ fontSize: 30, lineHeight: 1 }}>Study Pulse</div>
    <svg width="130" height="16" viewBox="0 0 130 16" aria-hidden="true"><path d="M2 11C18 13 38 8 62 10L68 10 72 3 77 15 82 10C100 9 114 12 128 8" fill="none" stroke="var(--ru)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
  </div>
);

const Avatar = ({ p }) => p.is_anonymous
  ? <div className="av"><span className="hw" style={{ fontSize: 15 }}>?</span></div>
  : <div className="av real hw">{p.display_name.slice(0, 2)}</div>;

export function Post({ p, detail, onOpen, onMeToo, onMessage }) {
  const open = detail ? undefined : () => onOpen(p.id);
  if (p.type === 'radar') {
    const due = new Date(p.due_at), soon = due - Date.now() < 864e5;
    return (
      <div className="note radar" onClick={open}>
        <div className="pin" />
        <div style={{ flex: 1 }}>
          <div className="hw" style={{ color: 'var(--ru)', fontSize: 18 }}>Radar caught this</div>
          <div style={{ fontSize: 16, fontWeight: 500, margin: '2px 0' }}>{p.radar_title}</div>
          <div className="mu" style={{ margin: '0 0 8px' }}>{p.display_name} · {ago(p.created_at)} · {left(p.due_at)}</div>
          <button className={'btn ' + (p.i_said_me_too ? 'me' : '')} onClick={e => { e.stopPropagation(); onMeToo(p.id); }}>{p.i_said_me_too ? 'Got it ✓' : 'Got it'} · {p.me_too_count}</button>
        </div>
        <div className={'stamp hw ' + (soon ? 'soon' : '')}>
          <div style={{ fontSize: 14, lineHeight: 1 }}>DUE</div>
          <div style={{ fontSize: 34, lineHeight: 1 }}>{due.getDate()}</div>
          <div style={{ fontSize: 15, lineHeight: 1 }}>{due.toLocaleString(undefined, { month: 'short' }).toUpperCase()} {due.toLocaleTimeString([], { hour: 'numeric' }).replace(' ', '').toUpperCase()}</div>
        </div>
      </div>
    );
  }
  return (
    <div className="note" onClick={open}>
      <div className="tape" />
      <div className="row" style={{ margin: '0 0 8px' }}>
        <Avatar p={p} />
        <div>
          {p.is_anonymous ? <span className="hw" style={{ fontSize: 20 }}>{p.display_name}</span> : <b>{p.display_name}</b>}
          <div className="mu">{ago(p.created_at)} · {p.topic}</div>
        </div>
      </div>
      <div>{p.content}</div>
      {p.photo_url && <img src={img(p.photo_url)} alt="Attached" style={{ width: '100%', borderRadius: 8, marginTop: 8 }} />}
      <div className="pulse hw" style={{ fontSize: 19 }}>{p.me_too_count} {p.me_too_count === 1 ? 'is' : 'are'} stuck here too</div>
      <div className="row">
        <button className={'btn ' + (p.i_said_me_too ? 'me' : 'r')} onClick={e => { e.stopPropagation(); onMeToo(p.id); }}>{p.i_said_me_too ? 'Me too ✓' : 'Me too'}</button>
        <button className="btn">{p.comment_count} comments</button>
        {!p.is_mine && <button className="btn" onClick={e => { e.stopPropagation(); onMessage(p.id); }}>Message</button>}
      </div>
    </div>
  );
}
