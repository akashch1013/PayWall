import { useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext.jsx';
import Field from '../components/Field.jsx';
import { useToast } from '../components/Toast.jsx';
import { validateLogin, validateSignup } from '../validation.js';

function redirectTarget(location) {
  const from = location.state?.from;
  return from ? `${from.pathname}${from.search ?? ''}` : '/';
}

/** Shared state and submit handling for the two auth forms. */
function useAuthForm(initial, validate, submit) {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const alertRef = useRef(null);

  const bind = (key) => ({
    value: values[key],
    onChange: (e) => {
      setValues((v) => ({ ...v, [key]: e.target.value }));
      if (errors[key]) setErrors(({ [key]: _removed, ...rest }) => rest);
    },
  });

  async function onSubmit(e) {
    e.preventDefault();
    setFormError('');
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length) return;
    setSubmitting(true);
    try {
      await submit(values);
    } catch (err) {
      setErrors(err.fields ?? {});
      setFormError(err.message);
      setSubmitting(false);
      alertRef.current?.focus();
    }
  }

  return { bind, errors, formError, submitting, onSubmit, alertRef };
}

function AuthCard({ subtitle, notice, form, children, footer }) {
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-logo" aria-hidden="true">
          Re<span>Wear</span>
        </div>
        <h1 className="auth-sub">{subtitle}</h1>
        {notice && <p className="alert alert-info">{notice}</p>}
        <div ref={form.alertRef} tabIndex={-1}>
          {form.formError && (
            <p className="alert alert-error" role="alert">
              {form.formError}
            </p>
          )}
        </div>
        {children}
        <div className="divider" />
        <p className="auth-switch">{footer}</p>
      </div>
    </div>
  );
}

export function Login() {
  const { user, login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const target = redirectTarget(location);
  const form = useAuthForm({ email: '', password: '' }, validateLogin, async ({ email, password }) => {
    const u = await login(email.trim(), password);
    toast(`Welcome back, ${u.name.split(' ')[0]}!`);
    navigate(target, { replace: true });
  });

  if (user && !form.submitting) return <Navigate to={target} replace />;

  return (
    <AuthCard
      subtitle="Welcome back! Log in to continue"
      notice={location.state?.reason}
      form={form}
      footer={
        <>
          Don't have an account?{' '}
          <Link to="/signup" state={location.state}>
            Sign up
          </Link>
        </>
      }
    >
      <form onSubmit={form.onSubmit} noValidate>
        <Field label="Email address" required error={form.errors.email}>
          <input type="email" autoComplete="email" placeholder="you@example.com" {...form.bind('email')} />
        </Field>
        <Field label="Password" required error={form.errors.password}>
          <input type="password" autoComplete="current-password" {...form.bind('password')} />
        </Field>
        <button type="submit" className="submit-btn" disabled={form.submitting} aria-busy={form.submitting}>
          {form.submitting ? 'Logging in…' : 'Log in'}
        </button>
      </form>
    </AuthCard>
  );
}

export function Signup() {
  const { user, register } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const target = redirectTarget(location);
  const form = useAuthForm({ name: '', email: '', password: '' }, validateSignup, async ({ name, email, password }) => {
    const u = await register(name.trim(), email.trim(), password);
    toast(`Welcome to ReWear, ${u.name.split(' ')[0]}!`);
    navigate(target, { replace: true });
  });

  if (user && !form.submitting) return <Navigate to={target} replace />;

  return (
    <AuthCard
      subtitle="Create a free account to buy and sell"
      notice={location.state?.reason}
      form={form}
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" state={location.state}>
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={form.onSubmit} noValidate>
        <Field label="Full name" required error={form.errors.name}>
          <input type="text" autoComplete="name" maxLength={80} placeholder="Priya Mehta" {...form.bind('name')} />
        </Field>
        <Field label="Email address" required error={form.errors.email}>
          <input type="email" autoComplete="email" placeholder="you@example.com" {...form.bind('email')} />
        </Field>
        <Field label="Password" required error={form.errors.password} hint="At least 8 characters">
          <input type="password" autoComplete="new-password" {...form.bind('password')} />
        </Field>
        <button type="submit" className="submit-btn" disabled={form.submitting} aria-busy={form.submitting}>
          {form.submitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </AuthCard>
  );
}
