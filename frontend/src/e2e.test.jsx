// End-to-end UI tests: the real React app in jsdom talking to a real running backend (see scripts/e2e.sh).
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from './App.jsx';

const API = import.meta.env.VITE_API_URL;
const uniq = () => Math.random().toString(36).slice(2, 8);

async function raw(path, { method = 'GET', body, token } = {}) {
  const r = await fetch(API + '/api' + path, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return r.status === 204 ? null : r.json();
}
const register = async (name) => { const u = 'u_' + uniq(); const r = await raw('/auth/register', { method: 'POST', body: { name, username: u, password: 'secret1' } }); return { token: r.token, username: u, name }; };

async function uiSignup(username, name = 'Tester') {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Create account' }));
  await user.type(screen.getByPlaceholderText(/Your name/), name);
  await user.type(screen.getByPlaceholderText(/^Username/), username);
  await user.type(screen.getByPlaceholderText(/^Password/), 'secret1');
  const btns = screen.getAllByRole('button', { name: 'Create account' });
  await user.click(btns[btns.length - 1]);
  expect(await screen.findByText('Save your recovery code')).toBeTruthy();
  expect(screen.getByText(/^[0-9A-F]{4}-[0-9A-F]{4}$/)).toBeTruthy();
  await user.click(screen.getByText('I saved it'));
  return user;
}
async function uiCreateClass(user, name = 'Physics, Grade 11') {
  await user.type(await screen.findByPlaceholderText(/Class name/), name);
  await user.click(screen.getByRole('button', { name: 'Create class' }));
  await screen.findByText('Stuck on this right now');
}
const openCompose = (user) => user.click(screen.getByRole('button', { name: 'New note' }));

describe('Study Pulse UI against the real API', () => {
  it('signs up, creates a class, posts anonymously, taps Me too', async () => {
    const user = await uiSignup('u_' + uniq());
    await uiCreateClass(user);
    await openCompose(user);
    await user.type(await screen.findByPlaceholderText('What are you stuck on?'), "Can't apply moment of inertia");
    await user.type(screen.getByPlaceholderText(/Topic/), 'Rotation');
    await user.click(screen.getAllByRole('button', { name: 'Post to class' })[0]);
    expect(await screen.findByText(/^Anon_\d{3}$/)).toBeTruthy();       // waits for the feed (the textarea also contains the note text)
    expect(screen.getByText("Can't apply moment of inertia")).toBeTruthy();
    expect(screen.queryByText('Tester')).toBeNull();                       // real name hidden
    expect(screen.getByText('0 are stuck here too')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Me too' }));
    expect(await screen.findByText('1 is stuck here too')).toBeTruthy();
    expect((await screen.findAllByText('Rotation')).length).toBeGreaterThan(0);   // topic bubble + chip
  });

  it('turns rough text into a stamped Radar deadline', async () => {
    const user = await uiSignup('u_' + uniq());
    await uiCreateClass(user);
    await openCompose(user);
    await user.type(await screen.findByPlaceholderText(/physics lab report due/), 'chemistry worksheet due friday 5pm');
    await user.click(screen.getByRole('button', { name: 'Read' }));
    const title = await screen.findByDisplayValue('Chemistry worksheet');
    expect(title).toBeTruthy();
    const posts = screen.getAllByRole('button', { name: 'Post to class' });
    await user.click(posts[posts.length - 1]);
    await user.click(await screen.findByRole('button', { name: 'Deadlines' }));
    expect(await screen.findByText('Chemistry worksheet')).toBeTruthy();
    expect(screen.getByText('DUE')).toBeTruthy();
  });

  it('DMs an anonymous poster, reveal and live replies work', async () => {
    const poster = await register('Pat Poster');
    const k = await raw('/classes', { method: 'POST', token: poster.token, body: { name: 'Bio 10' } });
    await raw(`/classes/${k.id}/posts`, { method: 'POST', token: poster.token, body: { type: 'struggle', content: 'Mitosis vs meiosis?', topic: 'Cells', is_anonymous: true } });

    const user = await uiSignup('u_' + uniq(), 'Vic Viewer');
    await user.type(await screen.findByPlaceholderText(/Class code/), k.code);
    await user.click(screen.getByRole('button', { name: 'Join' }));
    expect(await screen.findByText('Mitosis vs meiosis?')).toBeTruthy();
    expect(screen.queryByText('Pat Poster')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Message' }));
    expect((await screen.findAllByText('Anonymous student')).length).toBeGreaterThan(0);
    await user.type(screen.getByPlaceholderText('Write a message'), 'Want to study together?');
    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('Want to study together?')).toBeTruthy();

    const convs = await raw('/conversations', { token: poster.token });
    expect(convs[0].other_label).toBe('Vic Viewer');                          // poster sees the (non-anonymous) viewer
    await raw(`/conversations/${convs[0].id}/messages`, { method: 'POST', token: poster.token, body: { content: 'Yes! Thursday?' } });
    expect(await screen.findByText('Yes! Thursday?', {}, { timeout: 8000 })).toBeTruthy();   // arrives over the websocket
    await raw(`/conversations/${convs[0].id}/reveal`, { method: 'POST', token: poster.token });
    expect((await screen.findAllByText('Pat Poster', {}, { timeout: 8000 })).length).toBeGreaterThan(0);   // live reveal
  });

  it('signs out and back in; wrong password shows an error', async () => {
    const name = 'u_' + uniq();
    const user = await uiSignup(name);
    await uiCreateClass(user);
    await user.click(screen.getByRole('button', { name: 'Class' }));
    await user.click(await screen.findByRole('button', { name: 'Sign out' }));
    await user.type(await screen.findByPlaceholderText(/Username or phone/), name);
    await user.type(screen.getByPlaceholderText(/^Password/), 'wrongpass');
    const sign = () => screen.getAllByRole('button', { name: 'Sign in' }).at(-1);
    await user.click(sign());
    expect(await screen.findByText(/Wrong username\/phone or password/)).toBeTruthy();
    await user.clear(screen.getByPlaceholderText(/^Password/));
    await user.type(screen.getByPlaceholderText(/^Password/), 'secret1');
    await user.click(sign());
    expect(await screen.findByText('Stuck on this right now')).toBeTruthy();
  });

  it('class owner moderates a reported note', async () => {
    const user = await uiSignup('u_' + uniq());
    await uiCreateClass(user);
    await user.click(screen.getByRole('button', { name: 'Class' }));
    const code = (await screen.findByText(/^[0-9A-F]{6}$/)).textContent;
    const member = await register('Mia Member');
    await raw('/classes/join', { method: 'POST', token: member.token, body: { code } });
    const classes = await raw('/classes', { token: member.token });
    const p = await raw(`/classes/${classes[0].id}/posts`, { method: 'POST', token: member.token, body: { type: 'struggle', content: 'Rude note here', topic: 'Misc' } });
    await raw(`/posts/${p.id}/report`, { method: 'POST', token: member.token, body: { reason: 'rude' } });

    await user.click(screen.getByRole('button', { name: 'Home' }));
    await user.click(await screen.findByRole('button', { name: 'Class' }));
    const panel = (await screen.findByText('Moderation')).closest('.note');
    expect(await within(panel).findByText('Rude note here')).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: 'Remove note' }));
    await waitFor(() => expect(within(panel).queryByText('Rude note here')).toBeNull());
  });
});
