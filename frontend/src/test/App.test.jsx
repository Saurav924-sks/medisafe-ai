import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import App from '../App';
import { patient } from './fixtures/clinical';

const clinicianSession = { clinician_id: 7, display_name: 'Synthetic Test Clinician', roles: ['ADMIN', 'DOCTOR'] };
const ok = (value) => ({ ok: true, status: 200, json: async () => value });
function installApi({ authStatus = 200, authDetail, failPatients = null, failProfileTab = null, profileData = [], networkDown = false, roles = ['ADMIN', 'DOCTOR'] } = {}) {
  const calls = [];
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = new URL(url).pathname.replace('/api/v1', '');
    calls.push({ path, options });
    if (networkDown) throw new TypeError('Failed to fetch');
    if (path === '/auth/session') {
      if (authStatus !== 200) return { ok: false, status: authStatus, json: async () => ({ detail: authDetail || 'Authentication rejected.' }) };
      return ok({ ...clinicianSession, roles });
    }
    if (path === '/patients' && failPatients) return { ok: false, status: failPatients, json: async () => ({ detail: 'Patient service rejected the request.' }) };
    if (path === '/patients') return ok([patient]);
    if (path.includes('/medication-history') || path.includes('/observations') || path.includes('/encounters') || path.endsWith('/prescriptions')) {
      if (failProfileTab && path.endsWith(failProfileTab.endpoint)) {
        return { ok: false, status: 503, json: async () => ({ detail: 'Synthetic profile endpoint unavailable.' }) };
      }
      return ok(profileData);
    }
    if (path.startsWith('/patients/')) return ok(patient);
    return { ok: false, status: 404, json: async () => ({ detail: `Unexpected test endpoint ${path}` }) };
  });
  return calls;
}

async function signIn() {
  fireEvent.change(screen.getByRole('textbox', { name: 'Clinician ID' }), { target: { value: '7' } });
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'test-api-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('heading', { name: 'Patients' });
}

async function openPatient() {
  await screen.findByText('Synthetic Test Patient');
  fireEvent.click(screen.getByRole('button', { name: /Open profile/ }));
  await screen.findByRole('navigation', { name: 'Patient profile tabs' });
}

describe('protected clinical workflow', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    installApi();
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('signs in with clinician headers, stores credentials for the tab, and uses backend roles', async () => {
    const calls = installApi();
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getAllByText(/shared API key is a prototype boundary, not production authentication/i)).toHaveLength(2);
    await signIn();

    expect(screen.getByText(/Synthetic Test Clinician · ADMIN, DOCTOR/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Register patient/ })).toBeInTheDocument();
    expect(window.sessionStorage.length).toBe(1);
    expect(window.localStorage.length).toBe(0);
    expect(JSON.parse(window.sessionStorage.getItem('medisafe.clinicianCredentials'))).toEqual({ apiKey: 'test-api-key', clinicianId: '7' });

    for (const call of calls.filter(item => ['/auth/session', '/patients'].includes(item.path))) {
      expect(call.options.headers.get('X-API-Key')).toBe('test-api-key');
      expect(call.options.headers.get('X-Clinician-ID')).toBe('7');
    }
    expect(calls.some(call => call.path === '/auth/session')).toBe(true);
    await openPatient();
    expect(screen.getByRole('button', { name: 'New prescription' })).toBeEnabled();
  });

  it.each([
    [401, 'Sign-in failed (401)'],
    [403, 'Access denied (403)'],
    [503, 'Backend unavailable (503)'],
  ])('shows a distinct sign-in error for HTTP %i', async (status, message) => {
    installApi({ authStatus: status });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn().catch(() => {});
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('shows a visible backend-unreachable banner and a network sign-in error', async () => {
    installApi({ networkDown: true });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn().catch(() => {});
    expect(await screen.findByText(/Backend unreachable\. Check that the backend is running/)).toBeInTheDocument();
    expect(screen.getAllByRole('alert').some(alert => alert.textContent.includes('Backend unreachable'))).toBe(true);
  });

  it('restores saved credentials by revalidating the session endpoint', async () => {
    window.sessionStorage.setItem('medisafe.clinicianCredentials', JSON.stringify({ apiKey: 'saved-key', clinicianId: '7' }));
    const calls = installApi();
    render(<App />);
    await screen.findByRole('heading', { name: 'Patients' });
    expect(calls.find(call => call.path === '/auth/session').options.headers.get('X-API-Key')).toBe('saved-key');
    expect(screen.getByText(/Synthetic Test Clinician · ADMIN, DOCTOR/)).toBeInTheDocument();
  });

  it('clears the session and returns to sign-in when a protected request returns 401', async () => {
    installApi({ failPatients: 401 });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn().catch(() => {});
    await waitFor(() => {
      expect(window.sessionStorage.length).toBe(0);
      expect(screen.queryByText(/Synthetic Test Clinician/)).not.toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('uses read-only backend roles to keep write actions unavailable', async () => {
    installApi({ roles: ['READ_ONLY'] });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn();
    expect(screen.getByText(/Synthetic Test Clinician · READ_ONLY/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Register patient/ })).not.toBeInTheDocument();
    await openPatient();
    expect(screen.getByRole('button', { name: 'New prescription' })).toBeDisabled();
  });

  it('loads patient profile tab data from each connected read endpoint', async () => {
    const calls = installApi({
      profileData: [{ id: 31, medication_name: 'Synthetic medication', status: 'CURRENT', availability_status: 'KNOWN', value_text: 'Synthetic observation', code: 'synthetic-code', encounter_type: 'Synthetic encounter', started_at: '2026-01-01T00:00:00', orders: [] }],
    });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn();
    await openPatient();

    const tabEndpoints = [
      ['Medication History', '/patients/23/medication-history', 'Synthetic medication'],
      ['Observations', '/patients/23/observations', 'synthetic-code'],
      ['Encounters', '/patients/23/encounters', 'Synthetic encounter'],
      ['Prescriptions', '/patients/23/prescriptions', 'Prescription 31'],
    ];
    for (const [tabName, endpoint, expected] of tabEndpoints) {
      fireEvent.click(screen.getByRole('button', { name: tabName }));
      expect(await screen.findByText(new RegExp(expected, 'i'))).toBeInTheDocument();
      expect(calls.some(call => call.path === endpoint)).toBe(true);
    }

    fireEvent.click(screen.getByRole('button', { name: 'Audit' }));
    expect(screen.getByText(/Audit data unavailable/)).toBeInTheDocument();
  });

  it('shows loading, empty, and error states for connected patient profile tabs', async () => {
    const calls = installApi({ profileData: [] });
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn();
    await openPatient();

    fireEvent.click(screen.getByRole('button', { name: 'Observations' }));
    expect(await screen.findByText(/No observations records are available/)).toBeInTheDocument();
    expect(calls.some(call => call.path === '/patients/23/observations')).toBe(true);

    installApi({ failProfileTab: { endpoint: '/encounters' } });
    fireEvent.click(screen.getByRole('button', { name: 'Encounters' }));
    expect(await screen.findByText('Synthetic profile endpoint unavailable.')).toBeInTheDocument();
  });

  it('shows the loading state while a patient tab endpoint is pending', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn();
    await openPatient();
    let resolveObservations;
    global.fetch = vi.fn(url => {
      const path = new URL(url).pathname;
      if (path.endsWith('/observations')) {
        return new Promise(resolve => {
          resolveObservations = () => resolve(ok([]));
        });
      }
      return Promise.resolve(ok(patient));
    });

    fireEvent.click(screen.getByRole('button', { name: 'Observations' }));
    expect(screen.getByText('Loading observations…')).toBeInTheDocument();
    resolveObservations();
    expect(await screen.findByText(/No observations records are available/)).toBeInTheDocument();
  });

  it('signs out and clears tab-scoped credentials', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in' });
    await signIn();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(window.sessionStorage.length).toBe(0);
  });
});
