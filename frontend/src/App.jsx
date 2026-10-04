import { useEffect, useState } from 'react';
import { api, tok } from './api.js';
import { Logo } from './ui.jsx';
import { Auth, Chat, ClassTab, Compose, Detail, Home, Inbox, JoinClass, RadarTab } from './screens.jsx';

export default function App() {
  const [user, setUser] = useState(null), [ready, setReady] = useState(false), [classes, setClasses] = useState([]);
  const [cid, setCid] = useState(() => Number(localStorage.getItem('sp_cls')) || null), [view, setView] = useState({ n: 'home' }), [joining, setJoining] = useState(false);
  const go = (n, o = {}) => { setView({ n, ...o }); window.scrollTo(0, 0); };
  const refresh = async (pick) => {
    const cs = await api('/classes'); setClasses(cs);
    const next = pick || (cs.find(c => c.id === cid) ? cid : cs[0]?.id || null);
    setCid(next); next ? localStorage.setItem('sp_cls', next) : localStorage.removeItem('sp_cls');
  };
  useEffect(() => { (async () => { if (tok.get()) { try { setUser(await api('/me')); await refresh(); } catch { tok.set(null); } } setReady(true); })(); }, []);
  const signOut = () => { tok.set(null); localStorage.removeItem('sp_cls'); setUser(null); setClasses([]); setCid(null); setView({ n: 'home' }); setJoining(false); };
  if (!ready) return null;
  if (!user) return <Auth onAuth={async u => { await refresh(); setUser(u); }} />;
  const cls = classes.find(c => c.id === cid);
  if (!cls || joining) return <JoinClass onCancel={joining && classes.length ? () => setJoining(false) : undefined} onDone={async c => { setJoining(false); await refresh(c.id); go('home'); }} />;

  const tab = view.n === 'detail' ? 'home' : view.n === 'chat' ? 'inbox' : view.n;
  const screens = {
    home: <Home cid={cid} go={go} />,
    detail: <Detail id={view.id} me={{ anon: cls.my_anon_name }} go={go} back={() => go('home')} />,
    compose: <Compose cls={cls} done={t => go(t || 'home')} />,
    radar: <RadarTab cid={cid} />,
    inbox: <Inbox go={go} />,
    chat: <Chat id={view.id} back={() => go('inbox')} />,
    class: <ClassTab cls={cls} onJoinAnother={() => setJoining(true)} onSignOut={signOut} />,
  };
  const B = (k, l) => <button className={tab === k ? 'on' : ''} onClick={() => go(k)}>{l}</button>;
  return (<>
    {view.n === 'home' && <div className="row sp" style={{ margin: '0 0 8px' }}><Logo />
      <div style={{ textAlign: 'right' }}><select value={cid} onChange={e => { setCid(+e.target.value); localStorage.setItem('sp_cls', e.target.value); go('home'); }} aria-label="Class">{classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><div className="mu">{cls.member_count} in class</div></div></div>}
    {screens[view.n]}
    <div className="nav"><div>{B('home', 'Home')}{B('radar', 'Radar')}<button className="plus" aria-label="New note" onClick={() => go('compose')}>+</button>{B('inbox', 'Inbox')}{B('class', 'Class')}</div></div>
  </>);
}
