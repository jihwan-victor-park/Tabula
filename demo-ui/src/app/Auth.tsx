// Sign in / create account, and choosing or creating a store.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { SymbolIcon } from '../components/ui';
import { api, loadSession, saveSession, type Membership } from '../ops/api';
import { Badge, Button, ErrorBox, Field, Loading, Logo, Panel, inputCls, useMe } from '../ops/kit';

function AuthFrame({ title, sub, children }: { title: string; sub: ReactNode; children: ReactNode }) {
  return (
    <div className="grid min-h-screen bg-[#F7F3EE] font-[Plus_Jakarta_Sans,system-ui,sans-serif] text-[#16232B] lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden flex-col justify-between bg-[#1F3A4A] p-12 text-white lg:flex">
        <Logo light />
        <div>
          <h2 className="max-w-[460px] text-[34px] font-bold leading-tight tracking-[-0.02em]">Know what's on your shelves, and what to order next.</h2>
          <ul className="mt-6 flex flex-col gap-3 text-[15px] text-[#C9D6DD]">
            {['Bring in your sales and stock from a spreadsheet or Square', 'See what runs out soon — with the numbers behind it',
              'Count and adjust stock by scanning barcodes', 'Turn suggestions into supplier orders you approve'].map((t) => (
              <li key={t} className="flex gap-2"><SymbolIcon icon="check_circle" family="rounded" className="text-[20px] text-[#F29A85]" />{t}</li>
            ))}
          </ul>
        </div>
        <div className="text-[12px] text-[#8FA7B4]">Orders are never sent to suppliers without your approval.</div>
      </div>
      <div className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h1 className="text-[26px] font-bold tracking-[-0.01em]">{title}</h1>
          <p className="mt-1 text-[14px] text-[#5E6E78]">{sub}</p>
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function SignInPage({ mode }: { mode: 'signin' | 'signup' }) {
  const [params] = useSearchParams();
  const invite = mode === 'signup' ? params.get('invite') : null; // from a team invite link
  const [email, setEmail] = useState(params.get('email') ?? '');
  const [password, setPassword] = useState('');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const options = useQuery({ queryKey: ['auth-options'], queryFn: () => api<{ demo_sign_in: boolean }>('/auth/options', { noTenant: true }) });
  const submit = useMutation({
    mutationFn: () => api(`/auth/${mode === 'signin' ? 'login' : 'signup'}`, { body: mode === 'signup' ? { email, password, invite } : { email, password }, noTenant: true }),
    onSuccess: () => {
      const s = loadSession();
      if (s?.user) saveSession(null); // leave any demo sign-in behind
      qc.invalidateQueries({ queryKey: ['me'] });
      navigate(mode === 'signup' && !invite ? '/app/welcome' : params.get('next') || '/app/stores');
    },
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); submit.mutate(); };
  return (
    <AuthFrame title={mode === 'signin' ? 'Welcome back' : invite ? 'Join your team on Tabula' : 'Create your account'}
      sub={mode === 'signin' ? <>New to Tabula? <Link className="font-semibold text-[#B23F27] underline" to="/signup">Create an account</Link></>
        : <>Already have one? <Link className="font-semibold text-[#B23F27] underline" to="/signin">Sign in</Link></>}>
      <form className="flex flex-col gap-4" onSubmit={onSubmit}>
        <Field label="Email"><input className={inputCls} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
        <Field label="Password" hint={mode === 'signup' ? 'At least 10 characters.' : undefined}>
          <input className={inputCls} type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorBox error={submit.error} />
        <Button type="submit" size="lg" loading={submit.isPending}>{mode === 'signin' ? 'Sign in' : 'Create account'}</Button>
      </form>
      {options.data?.demo_sign_in && <DemoSignIn />}
    </AuthFrame>
  );
}

/** Email-only sign-in for demos on a developer's machine. Never offered on a real deployment. */
function DemoSignIn() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('owner@pawsandco.example');
  const navigate = useNavigate();
  const qc = useQueryClient();
  return (
    <div className="mt-8 rounded-[12px] border border-dashed border-[#CADBEE] bg-[#F1F6FC] p-4 text-[13px] text-[#24507F]">
      <button className="font-semibold underline" onClick={() => setOpen((o) => !o)}>Demo sign-in (developer machine only)</button>
      {open && (
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); saveSession({ tenantId: '', tenantName: '', user: email }); qc.clear(); navigate('/app/stores'); }}>
          <input className={`${inputCls} flex-1`} value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" variant="secondary">Continue</Button>
        </form>
      )}
    </div>
  );
}

const TYPES = [['pet', 'Pet supplies'], ['beauty', 'Beauty'], ['toys', 'Toys & games'], ['grocery', 'Grocery & deli'], ['gift', 'Gifts & home'],
  ['hardware', 'Hardware'], ['other', 'Something else']];
const ZONES = ['America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage',
  'Pacific/Honolulu', 'America/Toronto', 'Europe/London', 'Asia/Seoul'];

export function WelcomePage() {
  const me = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [form, setForm] = useState({ name: '', business_type: 'pet', timezone: ZONES.includes(tz) ? tz : 'America/New_York', currency: 'USD' });
  const create = useMutation({
    mutationFn: () => api<{ tenant_id: string; tenant_name: string; location_id: string }>('/stores', { body: form, noTenant: true }),
    onSuccess: (s) => {
      saveSession({ ...(loadSession()?.user ? { user: loadSession()!.user } : {}), tenantId: s.tenant_id, tenantName: s.tenant_name, locationId: s.location_id });
      qc.invalidateQueries({ queryKey: ['me'] });
      navigate('/app/data?welcome=1');
    },
  });
  if (me.isLoading) return <Loading />;
  return (
    <AuthFrame title="Set up your store" sub="Takes a minute. You can change these later in Settings.">
      <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Store name"><input className={inputCls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Corner Pet Supply" required /></Field>
        <Field label="What do you sell?">
          <select className={inputCls} value={form.business_type} onChange={(e) => setForm({ ...form, business_type: e.target.value })}>
            {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <div className="grid grid-cols-[1fr_110px] gap-3">
          <Field label="Time zone" hint="Used for “today”, delivery days and daily sales.">
            <select className={inputCls} value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
              {[...new Set([form.timezone, ...ZONES])].map((z) => <option key={z} value={z}>{z.replace('_', ' ')}</option>)}
            </select>
          </Field>
          <Field label="Currency">
            <select className={inputCls} value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
              {['USD', 'CAD', 'GBP', 'EUR', 'KRW'].map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
        </div>
        <ErrorBox error={create.error} />
        <Button type="submit" size="lg" loading={create.isPending}>Continue to your data</Button>
      </form>
      <div className="mt-6 text-center text-[13px] text-[#5E6E78]">Just looking? <Link className="font-semibold text-[#B23F27] underline" to="/app/stores">Open a sample store</Link></div>
    </AuthFrame>
  );
}

export function StoresPage() {
  const me = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const sample = useMutation({
    mutationFn: () => api<{ tenant_id: string }>('/sample-store', { method: 'POST', noTenant: true }),
    onSuccess: async (r) => { await qc.invalidateQueries({ queryKey: ['me'] }); const m = (await me.refetch()).data?.memberships.find((x) => x.tenant_id === r.tenant_id); if (m) open(m); },
  });
  const open = (m: Membership) => {
    const prev = loadSession();
    saveSession({ ...(prev?.user ? { user: prev.user } : {}), tenantId: m.tenant_id, tenantName: m.tenant_name, isSample: m.is_sample });
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' });
    navigate('/app');
  };
  if (me.isLoading) return <Loading />;
  if (!me.data) { navigate('/signin'); return null; }
  const real = me.data.memberships.filter((m) => !m.is_sample);
  const samples = me.data.memberships.filter((m) => m.is_sample);
  return (
    <AuthFrame title="Your stores" sub={me.data.email}>
      <div className="flex flex-col gap-2">
        {real.map((m) => (
          <button key={m.tenant_id} onClick={() => open(m)} className="flex items-center justify-between rounded-[14px] border border-[#E8E0D8] bg-white px-4 py-3 text-left hover:border-[#D3C5B8]">
            <span><span className="block text-[15px] font-semibold">{m.tenant_name}</span><span className="text-[12px] capitalize text-[#5E6E78]">{m.role}</span></span>
            <SymbolIcon icon="chevron_right" family="rounded" className="text-[22px] text-[#5E6E78]" />
          </button>
        ))}
        {real.length === 0 && <Panel><div className="text-[14px] text-[#5E6E78]">You don't have a store yet.</div></Panel>}
        <Link to="/app/welcome" className="mt-1"><Button variant={real.length ? 'secondary' : 'primary'} size="lg">{real.length ? 'Add another store' : 'Set up your store'}</Button></Link>
      </div>
      <div className="mt-8 border-t border-[#E8E0D8] pt-6">
        <div className="mb-2 flex items-center gap-2 text-[14px] font-semibold">Sample store <Badge tone="info">fictional data</Badge></div>
        <p className="mb-3 text-[13px] text-[#5E6E78]">A pet shop with 4 weeks of sales, two suppliers and stock already loaded — to try every screen. It stays separate from your own store.</p>
        {samples.map((m) => <Button key={m.tenant_id} variant="secondary" onClick={() => open(m)}>Open {m.tenant_name}</Button>)}
        {samples.length === 0 && <Button variant="secondary" onClick={() => sample.mutate()} loading={sample.isPending}>Create a sample store</Button>}
        <ErrorBox error={sample.error} />
      </div>
    </AuthFrame>
  );
}
