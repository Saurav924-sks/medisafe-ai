const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
const API_BASE_URL = configuredBaseUrl.endsWith('/api/v1') ? configuredBaseUrl : `${configuredBaseUrl}/api/v1`;
const SESSION_STORAGE_KEY = 'medisafe.clinicianCredentials';

export class ApiError extends Error {
  constructor(message, { status = null, kind = 'http' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
  }
}

function notify(type, detail) {
  window.dispatchEvent(new CustomEvent(type, { detail }));
}

export function getStoredCredentials() {
  const stored = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!stored) return null;
  try {
    const credentials = JSON.parse(stored);
    if (typeof credentials.apiKey === 'string' && typeof credentials.clinicianId === 'string') {
      return credentials;
    }
  } catch {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  }
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  return null;
}

export function clearStoredCredentials() {
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

async function request(path, options = {}, credentials = getStoredCredentials()) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (credentials) {
    headers.set('X-API-Key', credentials.apiKey);
    headers.set('X-Clinician-ID', credentials.clinicianId);
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    notify('medisafe-backend-status', { unreachable: false });
  } catch {
    notify('medisafe-backend-status', { unreachable: true });
    throw new ApiError('Backend unreachable. Check that the backend is running and try again.', { kind: 'network' });
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : payload.detail?.message;
    if (response.status === 401) {
      clearStoredCredentials();
      notify('medisafe-auth-expired');
    }
    throw new ApiError(detail || `Request failed (${response.status}).`, { status: response.status });
  }
  return payload;
}

export async function login(apiKey, clinicianId) {
  const credentials = { apiKey: apiKey.trim(), clinicianId: String(clinicianId).trim() };
  const session = await request('/auth/session', {}, credentials);
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(credentials));
  return session;
}

export async function restoreSession() {
  const credentials = getStoredCredentials();
  if (!credentials) return null;
  return request('/auth/session', {}, credentials);
}

export function logout() {
  clearStoredCredentials();
}

export const listPatients = () => request('/patients');
export const getPatient = (patientId) => request(`/patients/${patientId}`);
export const getPatientMedicationHistory = (patientId) => request(`/patients/${patientId}/medication-history`);
export const getPatientObservations = (patientId) => request(`/patients/${patientId}/observations`);
export const getPatientEncounters = (patientId) => request(`/patients/${patientId}/encounters`);
export const getPatientPrescriptions = (patientId) => request(`/patients/${patientId}/prescriptions`);
export const createPatient = (patientData) => request('/patients', { method: 'POST', body: JSON.stringify(patientData) });
export const addPatientAllergy = (patientId, allergyName) => request(`/patients/${patientId}/allergies`, { method: 'POST', body: JSON.stringify({ allergy_name: allergyName }) });
export const addPatientCondition = (patientId, conditionName) => request(`/patients/${patientId}/conditions`, { method: 'POST', body: JSON.stringify({ condition_name: conditionName }) });
export const addPatientMedication = (patientId, medData) => request(`/patients/${patientId}/medications`, { method: 'POST', body: JSON.stringify(medData) });
export const createPrescription = (data) => request('/prescriptions', { method: 'POST', body: JSON.stringify(data) });
export const getPrescription = (id) => request(`/prescriptions/${id}`);
export const confirmNormalization = (id) => request(`/prescriptions/${id}/confirm-normalization`, { method: 'POST' });
export const runPrescriptionAnalysis = (id) => request(`/prescriptions/${id}/analyze`, { method: 'POST' });
export const getAlertQueue = () => request('/alerts/review-queue');
export const submitAlertAction = (id, action, fields = {}) => request(`/alerts/${id}/actions`, { method: 'POST', body: JSON.stringify({ action, ...fields }) });
export const submitAlertFeedback = (id, analysisId, feedback, rationale) => request(`/alerts/${id}/feedback`, { method: 'POST', body: JSON.stringify({ analysis_id: analysisId, feedback, rationale }) });
export const getFeedbackAnalytics = () => request('/feedback/analytics');
export const reevaluateAnalysis = (analysisId) => request(`/prescriptions/analyze/${analysisId}/reevaluate`, { method: 'POST' });
export const getSystemStatus = () => request('/system/status');
