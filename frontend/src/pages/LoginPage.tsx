import { ArrowRight, Eye, EyeOff } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { useAuth } from '@/components/providers';
import { Button, Field } from '@/components/ui';
import { isMFAChallenge } from '@/lib/mfa-api';

export function LoginPage() {
  const { session, login } = useAuth(); const navigate = useNavigate(); const location = useLocation();
  const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState('');
  if (session) return <Navigate to={session.user.emailVerified === false ? '/verify-email' : '/'} replace />;
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (!/^\S+@\S+\.\S+$/.test(email)) { setError('Enter a valid email address.'); return; }
    if (password.length < 6) { setError('Password must be at least 6 characters.'); return; }
    setSubmitting(true);
    try {
      const target = (location.state as { from?: string } | null)?.from ?? '/';
      const signedIn = await login(email, password);
      if (isMFAChallenge(signedIn)) {
        navigate('/mfa-challenge', {
          replace: true,
          state: { challengeToken: signedIn.challengeToken, from: target },
        });
        return;
      }
      if (signedIn.user.emailVerified === false) {
        navigate('/verify-email', { replace: true });
        return;
      }
      navigate(target, { replace: true });
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'We could not sign you in.'); }
    finally { setSubmitting(false); }
  };
  return <div className="login-page">
    <section className="login-panel">
      <div className="login-panel__inner">
        <Brand />
        <div className="login-heading"><h1>Welcome back</h1><p>Sign in to train, test, and improve your AI agents.</p></div>
        <form className="login-form" onSubmit={(event) => void submit(event)} noValidate>
          <Field label="Work email" htmlFor="email"><input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="email" autoFocus /></Field>
          <Field label="Password" htmlFor="password">
            <div className="password-input"><input id="password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" autoComplete="current-password" /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff /> : <Eye />}</button></div>
          </Field>
          <div className="login-options"><label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> Keep me signed in</label><Link className="text-button" to="/forgot-password">Forgot password?</Link></div>
          {error ? <div className="form-error" role="alert">{error}</div> : null}
          <Button size="lg" type="submit" disabled={submitting}>{submitting ? <span className="button-spinner" /> : <>Sign in <ArrowRight /></>}</Button>
        </form>
        <p className="signup-copy">New to Northstar? <Link className="text-button" to="/signup">Create an account</Link></p>
        <p className="login-legal">By continuing, you agree to our <a href="#terms">Terms</a> and <a href="#privacy">Privacy Policy</a>.</p>
      </div>
    </section>
  </div>;
}
