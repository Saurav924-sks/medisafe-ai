import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, ArrowLeft, ClipboardList, Plus, Search, UserRound } from 'lucide-react';
import {
  addPatientAllergy, addPatientCondition, addPatientMedication, confirmNormalization, createPatient,
  clearStoredCredentials, createPrescription, getAlertQueue, getPatient, getPatientEncounters,
  getPatientMedicationHistory, getPatientObservations, getPatientPrescriptions, getPrescription, listPatients, login,
  logout, restoreSession, runPrescriptionAnalysis, submitAlertAction,
} from './services/api';

const profileTabs = ['Summary', 'Demographics', 'Allergies', 'Conditions', 'Current Meds', 'Medication History', 'Observations', 'Encounters', 'Prescriptions', 'Safety Analysis', 'Audit'];
const writableRoles = ['ADMIN', 'DOCTOR', 'PHARMACIST'];
const overrideRoles = ['ADMIN', 'DOCTOR', 'CLINICAL_REVIEWER'];

function ErrorMessage({ children }) { return <div role="alert" className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900">{children}</div>; }
function Notice({ children, tone = 'slate' }) { const tones = { slate: 'bg-slate-50 border-slate-200 text-slate-700', amber: 'bg-amber-50 border-amber-300 text-amber-950', blue: 'bg-blue-50 border-blue-200 text-blue-900' }; return <div className={`rounded border p-3 text-sm ${tones[tone]}`}>{children}</div>; }
function Field({ label, status = 'Optional', children }) { return <label className="block text-sm font-medium text-slate-700">{label}<span className="ml-2 text-xs font-normal text-slate-500">{status}</span>{children}</label>; }
function SourceFreshness() { return <p className="text-xs text-slate-500">Source: legacy patient record · Freshness: not available · Verification: unknown</p>; }

function PatientList({ onSelect, canRegister }) {
  const [patients, setPatients] = useState([]); const [query, setQuery] = useState(''); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [showRegister, setShowRegister] = useState(false); const [saving, setSaving] = useState(false); const [formError, setFormError] = useState('');
  const [form, setForm] = useState({ name: '', age: '', gender: '' });
  function load() { setLoading(true); setError(''); listPatients().then(setPatients).catch(e => setError(e.message)).finally(() => setLoading(false)); }
  useEffect(() => {
    let active = true;
    listPatients()
      .then(items => { if (active) setPatients(items); })
      .catch(error => { if (active) setError(error.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const filtered = useMemo(() => patients.filter(p => `${p.name} ${p.id}`.toLowerCase().includes(query.toLowerCase().trim())), [patients, query]);
  async function register(event) { event.preventDefault(); setSaving(true); setFormError(''); try { const patient = await createPatient({ name: form.name.trim(), age: Number(form.age), gender: form.gender }); setPatients(items => [patient, ...items]); setShowRegister(false); setForm({ name: '', age: '', gender: '' }); onSelect(patient); } catch (e) { setFormError(e.message); } finally { setSaving(false); } }
  return <section className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-2xl font-bold">Patients</h2><p className="text-sm text-slate-600">Search the organization patient list or register a patient.</p></div>{canRegister && <button onClick={() => setShowRegister(v => !v)} className="inline-flex items-center gap-2 rounded bg-blue-800 px-4 py-2 text-white"><Plus size={17}/> Register patient</button>}</div>
    {showRegister && <form onSubmit={register} className="grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-3"><Field label="Full name" status="Required"><input required maxLength="100" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="mt-1 w-full rounded border p-2"/></Field><Field label="Age in years" status="Required"><input required type="number" min="0" max="120" value={form.age} onChange={e => setForm({ ...form, age: e.target.value })} className="mt-1 w-full rounded border p-2"/></Field><Field label="Gender" status="Required"><select required value={form.gender} onChange={e => setForm({ ...form, gender: e.target.value })} className="mt-1 w-full rounded border p-2"><option value="">Select</option><option>Female</option><option>Male</option><option>Other</option><option>Unknown</option></select></Field>{formError && <div className="sm:col-span-3"><ErrorMessage>{formError}</ErrorMessage></div>}<div className="flex gap-2 sm:col-span-3"><button disabled={saving} className="rounded bg-blue-800 px-4 py-2 text-white">{saving ? 'Registering…' : 'Register'}</button><button type="button" onClick={() => setShowRegister(false)} className="rounded border px-4 py-2">Cancel</button></div></form>}
    <div className="relative"><Search className="absolute left-3 top-3 text-slate-400" size={18}/><input aria-label="Search patients" placeholder="Search by patient name or ID" value={query} onChange={e => setQuery(e.target.value)} className="w-full rounded-lg border bg-white py-2.5 pl-10 pr-3"/></div>
    {loading ? <Notice>Loading patient list…</Notice> : error ? <div className="space-y-3"><ErrorMessage>{error}</ErrorMessage><button onClick={load} className="rounded border px-3 py-2">Retry</button></div> : filtered.length === 0 ? <Notice>{query ? 'No patients match this search.' : 'No patients are registered yet.'}</Notice> : <div className="overflow-hidden rounded-xl border bg-white">{filtered.map(p => <button key={p.id} onClick={() => onSelect(p)} className="flex w-full items-center justify-between border-b p-4 text-left last:border-b-0 hover:bg-blue-50"><span><span className="block font-semibold">{p.name}</span><span className="text-sm text-slate-500">Patient ID {p.id} · {p.age ?? 'Age not available'} years · {p.gender || 'Gender unknown'}</span></span><span className="text-sm text-blue-800">Open profile →</span></button>)}</div>}
  </section>;
}

function PatientProfile({ patient: initialPatient, session, onBack, onNewPrescription }) {
  const [patient, setPatient] = useState(initialPatient); const [tab, setTab] = useState('Summary'); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [entry, setEntry] = useState(''); const [entryError, setEntryError] = useState(''); const [saving, setSaving] = useState(false);
  const [tabResult, setTabResult] = useState(null);
  const canEdit = session.roles.some(role => writableRoles.includes(role));
  useEffect(() => { let active = true; getPatient(initialPatient.id).then(p => active && setPatient(p)).catch(e => active && setError(e.message)).finally(() => active && setLoading(false)); return () => { active = false; }; }, [initialPatient.id]);
  useEffect(() => {
    const loaders = {
      'Medication History': getPatientMedicationHistory,
      Observations: getPatientObservations,
      Encounters: getPatientEncounters,
      Prescriptions: getPatientPrescriptions,
    };
    const load = loaders[tab];
    if (!load) return undefined;
    let active = true;
    load(patient.id)
      .then(data => { if (active) setTabResult({ key: `${patient.id}:${tab}`, data }); })
      .catch(loadError => { if (active) setTabResult({ key: `${patient.id}:${tab}`, error: loadError.message }); });
    return () => { active = false; };
  }, [patient.id, tab]);
  async function addEntry(event) { event.preventDefault(); if (!entry.trim()) return; setSaving(true); setEntryError(''); try { if (tab === 'Allergies') await addPatientAllergy(patient.id, entry.trim()); else if (tab === 'Conditions') await addPatientCondition(patient.id, entry.trim()); else await addPatientMedication(patient.id, { medication_name: entry.trim() }); setPatient(await getPatient(patient.id)); setEntry(''); } catch (e) { setEntryError(e.message); } finally { setSaving(false); } }
  if (loading) return <Notice>Loading patient profile…</Notice>;
  if (error) return <div className="space-y-3"><ErrorMessage>{error}</ErrorMessage><button onClick={onBack} className="rounded border px-3 py-2">Back to patients</button></div>;
  const unavailableTabs = ['Audit'];
  const tabKey = `${patient.id}:${tab}`;
  const tabLoading = ['Medication History', 'Observations', 'Encounters', 'Prescriptions'].includes(tab)
    && tabResult?.key !== tabKey;
  const tabError = tabResult?.key === tabKey ? tabResult.error : '';
  const tabData = tabResult?.key === tabKey ? tabResult.data : null;
  const listForTab = tab === 'Allergies' ? patient.allergies || [] : tab === 'Conditions' ? patient.conditions || [] : patient.current_meds || [];
  return <section className="space-y-5">
    <button onClick={onBack} className="inline-flex items-center gap-2 text-sm text-blue-800"><ArrowLeft size={16}/> Patients</button>
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-white p-5"><div><h2 className="text-2xl font-bold">{patient.name}</h2><p className="text-sm text-slate-600">Patient ID {patient.id}</p><SourceFreshness/></div><button disabled={!canEdit} onClick={onNewPrescription} className="rounded bg-blue-800 px-4 py-2 text-white disabled:opacity-50">New prescription</button></div>
    <div className="overflow-x-auto rounded-lg border bg-white"><nav aria-label="Patient profile tabs" className="flex min-w-max">{profileTabs.map(item => <button key={item} onClick={() => { setTab(item); setEntryError(''); }} aria-current={tab === item ? 'page' : undefined} className={`border-b-2 px-4 py-3 text-sm ${tab === item ? 'border-blue-800 font-semibold text-blue-900' : 'border-transparent text-slate-600'}`}>{item}</button>)}</nav></div>
    {tab === 'Summary' && <div className="grid gap-4 md:grid-cols-2"><Notice tone="blue"><strong>Data quality</strong><p className="mt-1">Legacy profile data. Verification and freshness are unknown.</p></Notice><Notice><strong>Safety context</strong><p className="mt-1">Missing or unverified information is not treated as absent.</p></Notice><button onClick={() => setTab('Allergies')} className="rounded-xl border bg-white p-4 text-left">Allergies <span className="block text-sm text-slate-500">{patient.allergies?.length || 0} recorded</span></button><button onClick={() => setTab('Current Meds')} className="rounded-xl border bg-white p-4 text-left">Current medications <span className="block text-sm text-slate-500">{patient.current_meds?.length || 0} recorded</span></button></div>}
    {tab === 'Demographics' && <div className="grid gap-3 rounded-xl border bg-white p-5 sm:grid-cols-2"><p>Name <b>{patient.name || 'Not available'}</b></p><p>Age <b>{patient.age ?? 'Unknown'}</b></p><p>Gender <b>{patient.gender || 'Unknown'}</b></p><p>Date of birth <b>Not available</b></p><SourceFreshness/></div>}
    {['Allergies', 'Conditions', 'Current Meds'].includes(tab) && <div className="space-y-4 rounded-xl border bg-white p-5"><div><h3 className="font-semibold">{tab}</h3><SourceFreshness/></div>{canEdit && <form onSubmit={addEntry} className="flex flex-wrap gap-2"><Field label={tab === 'Allergies' ? 'Allergen' : tab === 'Conditions' ? 'Condition' : 'Medication name'} status="Required"><input required value={entry} onChange={e => setEntry(e.target.value)} className="mt-1 min-w-64 rounded border p-2"/></Field>{tab === 'Current Meds' && <p className="self-end pb-2 text-xs text-slate-500">Dose and frequency: not available in this form</p>}<button disabled={saving} className="self-end rounded bg-blue-800 px-4 py-2 text-white">{saving ? 'Saving…' : 'Add record'}</button></form>}{entryError && <ErrorMessage>{entryError}</ErrorMessage>}{listForTab.length ? <ul className="divide-y">{listForTab.map((item, i) => <li key={i} className="py-3">{item.allergy_name || item.condition_name || item.medication_name}{item.dose ? ` · ${item.dose}` : ''}<span className="ml-2 text-xs text-slate-500">Verification: unknown</span></li>)}</ul> : <Notice>No entries are recorded. The record’s completeness is unknown.</Notice>}</div>}
    {unavailableTabs.includes(tab) && <Notice><strong>{tab} data unavailable</strong><p className="mt-1">This deployment has no connected endpoint for this record type. No entries are inferred.</p></Notice>}
    {['Medication History', 'Observations', 'Encounters', 'Prescriptions'].includes(tab) && <section aria-label={`${tab} records`} className="space-y-3 rounded-xl border bg-white p-5">
      <h3 className="font-semibold">{tab}</h3>
      {tabLoading ? <Notice>Loading {tab.toLowerCase()}…</Notice> : tabError ? <ErrorMessage>{tabError}</ErrorMessage> : tabData?.length === 0 ? <Notice>No {tab.toLowerCase()} records are available. Data completeness is unknown.</Notice> : tabData?.length > 0 ? <ul className="divide-y">{tabData.map(record => <li key={record.id} className="space-y-1 py-3">
        {tab === 'Medication History' && <><p className="font-medium">{record.medication_name}</p><p className="text-sm text-slate-600">Status: {record.status} · Dose: {record.dose ?? 'Not available'} · Frequency: {record.frequency ?? 'Not available'}</p></>}
        {tab === 'Observations' && <><p className="font-medium">{record.code}</p><p className="text-sm text-slate-600">Status: {record.availability_status} · Value: {record.value_text ?? record.value_number ?? 'Not available'} {record.unit ?? ''}</p></>}
        {tab === 'Encounters' && <><p className="font-medium">{record.encounter_type ?? 'Encounter type not available'}</p><p className="text-sm text-slate-600">Status: {record.status} · Started: {record.started_at ?? 'Not available'}</p></>}
        {tab === 'Prescriptions' && <><p className="font-medium">Prescription {record.id} · {record.status}</p><p className="text-sm text-slate-600">{record.orders?.length ?? 0} medication orders · Created: {record.created_at ?? 'Not available'}</p></>}
      </li>)}</ul> : null}
    </section>}
    {tab === 'Safety Analysis' && <Notice>Select “New prescription” to run an analysis. Analyses report checked and not-checked domains and do not establish clinical safety.</Notice>}
  </section>;
}

function PrescriptionWorkflow({ patient, canAnalyze, canReview, onBack }) {
  const blank = () => ({ medication_name: '', dose: '', unit: '', route: '', frequency: '', duration: '' });
  const [order, setOrder] = useState(blank); const [prescription, setPrescription] = useState(null); const [analysis, setAnalysis] = useState(null); const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [override, setOverride] = useState({});
  async function saveDraft(event) { event.preventDefault(); setLoading(true); setError(''); setAnalysis(null); try { const result = await createPrescription({ patient_id: patient.id, medication_orders: [{ ...order, dose: Number(order.dose) }] }); setPrescription(result); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  async function confirm() { setLoading(true); setError(''); try { await confirmNormalization(prescription.id); setPrescription(await getPrescription(prescription.id)); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  async function analyze() { setLoading(true); setError(''); try { setAnalysis(await runPrescriptionAnalysis(prescription.id)); } catch (e) { setError(e.message); setAnalysis({ analysis_status: 'FAILED', safety_domains: {}, alerts: [], data_quality: { failure: 'Analysis service unavailable' } }); } finally { setLoading(false); } }
  async function action(alertId, actionName) { setLoading(true); setError(''); try { const fields = actionName === 'OVERRIDE' ? override[alertId] || {} : {}; await submitAlertAction(alertId, actionName, fields); setAnalysis(prev => ({ ...prev, alerts: actionName === 'ACKNOWLEDGE' || actionName === 'REVIEW' ? prev.alerts.map(a => a.id === alertId ? { ...a, review_status: actionName } : a) : prev.alerts.filter(a => a.id !== alertId) })); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  return <section className="space-y-5"><button onClick={onBack} className="inline-flex items-center gap-2 text-sm text-blue-800"><ArrowLeft size={16}/> Patient profile</button><div><h2 className="text-2xl font-bold">Prescription</h2><p className="text-sm text-slate-600">Patient: {patient.name} · ID {patient.id}</p><p className="text-xs text-slate-500">Patient context source: legacy record · freshness: unavailable · allergy verification: unknown</p></div>
    {!prescription && <form onSubmit={saveDraft} className="space-y-4 rounded-xl border bg-white p-5"><h3 className="font-semibold">Structured medication entry</h3><div className="grid gap-4 md:grid-cols-2"><Field label="Medication name" status="Required"><input required value={order.medication_name} onChange={e => setOrder({ ...order, medication_name: e.target.value })} className="mt-1 w-full rounded border p-2"/></Field><Field label="Dose" status="Required"><input required type="number" min="0.000001" step="any" value={order.dose} onChange={e => setOrder({ ...order, dose: e.target.value })} className="mt-1 w-full rounded border p-2"/></Field><Field label="Dose unit" status="Required"><select required value={order.unit} onChange={e => setOrder({ ...order, unit: e.target.value })} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{['mg','mcg','g','mL','unit','tablet','capsule'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="Route" status="Required"><select required value={order.route} onChange={e => setOrder({ ...order, route: e.target.value })} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{['oral','intravenous','intramuscular','subcutaneous','topical','inhalation','rectal','ophthalmic','otic','sublingual','transdermal'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="Frequency" status="Required"><select required value={order.frequency} onChange={e => setOrder({ ...order, frequency: e.target.value })} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{['once','once daily','twice daily','three times daily','four times daily','every 4 hours','every 6 hours','every 8 hours','every 12 hours','as needed'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="Duration" status="Optional"><input value={order.duration} onChange={e => setOrder({ ...order, duration: e.target.value })} className="mt-1 w-full rounded border p-2"/></Field></div><Notice>Normalization status is unknown until the backend checks the submitted medication. Unknown or ambiguous matches cannot proceed to analysis.</Notice><button disabled={!canAnalyze || loading} className="rounded bg-blue-800 px-4 py-2 text-white disabled:opacity-50">{loading ? 'Saving draft…' : 'Validate and save draft'}</button></form>}
    {prescription && <div className="space-y-4 rounded-xl border bg-white p-5"><h3 className="font-semibold">Normalization confirmation</h3><div className="rounded border p-4"><p className="font-medium">{prescription.orders?.[0]?.medication_name}</p><p className="text-sm">Dose: {prescription.orders?.[0]?.dose ?? 'Unknown'} {prescription.orders?.[0]?.unit ?? 'unit not available'} · Route: {prescription.orders?.[0]?.route ?? 'Unknown'} · Frequency: {prescription.orders?.[0]?.frequency ?? 'Unknown'}</p><p className="mt-2 text-sm">Status: {prescription.orders?.[0]?.normalization_status ?? 'Unknown'} · Confidence: {prescription.orders?.[0]?.normalization_confidence ?? 'Not available'}</p><p className="text-sm">Matched concept: {prescription.orders?.[0]?.canonical_entity?.name || 'Not available'}</p><p className="text-sm text-slate-500">{prescription.orders?.[0]?.normalization_message || 'Review the normalized name and source before confirming.'}</p></div>{prescription.orders?.[0]?.normalization_status === 'NORMALIZED' && !prescription.orders?.[0]?.normalization_confirmed && canAnalyze && <button disabled={loading} onClick={confirm} className="rounded border border-blue-800 px-4 py-2 text-blue-900">{loading ? 'Confirming…' : 'Confirm normalized medication'}</button>}{prescription.orders?.[0]?.normalization_status !== 'NORMALIZED' && <Notice tone="amber">Medication could not be confidently normalized. Review required. Analysis is unavailable for this item.</Notice>}{prescription.orders?.[0]?.normalization_confirmed && <button disabled={loading || !canAnalyze} onClick={analyze} className="rounded bg-blue-800 px-4 py-2 text-white">{loading ? 'Running analysis…' : 'Run analysis'}</button>}</div>}
    {error && <ErrorMessage>{error}</ErrorMessage>}
    {analysis && <div className="space-y-4"><section className="rounded-xl border bg-white p-5"><h3 className="text-xl font-bold">Analysis results</h3><p className="mt-1 inline-flex rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold">Status: {analysis.analysis_status}</p><p className="mt-2 text-sm">Rule set: {analysis.rule_set_version || 'Not available'} · Knowledge version: {analysis.knowledge_version || 'Not available'}</p><p className="text-sm">Data freshness: {analysis.data_quality?.freshness || 'Not available'} · Allergy verification: {analysis.data_quality?.allergy_verification || 'Unknown'}</p><h4 className="mt-4 font-semibold">Checked domains</h4><p className="text-sm">{Object.entries(analysis.safety_domains || {}).filter(([,v]) => v === 'EVALUATED' || v === true).map(([k]) => k.replaceAll('_',' ')).join(', ') || 'None'}</p><h4 className="mt-2 font-semibold">Not checked</h4><p className="text-sm">{Object.entries(analysis.safety_domains || {}).filter(([,v]) => v !== 'EVALUATED' && v !== true).map(([k]) => k.replaceAll('_',' ')).join(', ') || 'None reported'}</p></section>
    {analysis.analysis_status === 'FAILED' ? <Notice tone="amber">Analysis failed. No safety domains were evaluated. Correct the service issue before relying on any result.</Notice> : analysis.alerts?.length ? analysis.alerts.map(alert => <article key={alert.id} className={`rounded-xl border-l-4 bg-white p-5 shadow-sm ${alert.severity === 'CRITICAL' ? 'border-rose-700' : alert.severity === 'HIGH' ? 'border-orange-600' : alert.severity === 'MODERATE' ? 'border-amber-500' : 'border-blue-500'}`}><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wide">{alert.severity} · {alert.type}</p><h4 className="mt-1 font-semibold">{alert.what_detected}</h4>{alert.review_status && <p className="text-sm text-slate-600">{alert.review_status.toLowerCase()} by clinician</p>}</div><AlertTriangle aria-hidden="true" className="text-slate-500"/></div><details className="mt-3"><summary className="cursor-pointer font-medium">Why was this flagged?</summary><p className="mt-1 text-sm">{alert.why_flagged || 'Insufficient data to evaluate.'}</p></details><details className="mt-2"><summary className="cursor-pointer font-medium">What information was used?</summary><p className="mt-1 text-sm">{alert.trigger_info || 'Available patient context and confirmed prescription fields.'}</p></details><details className="mt-2"><summary className="cursor-pointer font-medium">What was unavailable?</summary><p className="mt-1 text-sm">{Object.entries(analysis.data_quality || {}).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`).join('; ') || 'Not available'}</p></details><p className="mt-3 text-xs">Rule: {alert.rule_id || 'Not available'} · Version: {alert.rule_version || 'Not available'} · Evidence: {alert.evidence || 'Not available'} · Source: {alert.source || 'Not available'}</p><div className="mt-4 flex flex-wrap gap-2"><button disabled={!canReview || loading || alert.review_status === 'REVIEW'} onClick={() => action(alert.id,'REVIEW')} className="rounded border px-3 py-2 text-sm">Review</button><button disabled={!canReview || loading || alert.review_status === 'ACKNOWLEDGE'} onClick={() => action(alert.id,'ACKNOWLEDGE')} className="rounded border px-3 py-2 text-sm">Acknowledge</button>{canReview && <OverrideControl alertId={alert.id} values={override[alert.id] || {}} onChange={value => setOverride(current => ({ ...current, [alert.id]: value }))} onSubmit={() => action(alert.id,'OVERRIDE')} disabled={loading}/>}<button disabled={!canReview || loading} onClick={() => action(alert.id,'RESOLVE')} className="rounded border px-3 py-2 text-sm">Resolve</button><button disabled={!canReview || loading} onClick={() => action(alert.id,'DISMISS')} className="rounded border px-3 py-2 text-sm">Dismiss</button></div></article>) : <Notice>No alerts were returned for the evaluated domains. Not all domains were checked.</Notice>}</div>}
  </section>;
}

function OverrideControl({ alertId, values, onChange, onSubmit, disabled }) {
  return <div className="flex flex-wrap items-end gap-2"><label className="text-xs">Override reason (required for high/critical)<select aria-label={`Override reason for alert ${alertId}`} value={values.override_reason || ''} onChange={e => onChange({ ...values, override_reason: e.target.value })} className="mt-1 block rounded border p-2"><option value="">Select reason</option>{['CLINICAL_JUDGMENT','PATIENT_CONTEXT_NOT_CAPTURED','DUPLICATE_OR_ALREADY_ADDRESSED','REFERENCE_DATA_ISSUE','OTHER'].map(x => <option key={x}>{x}</option>)}</select></label>{values.override_reason === 'OTHER' && <label className="text-xs">Details (optional)<input value={values.override_reason_text || ''} onChange={e => onChange({ ...values, override_reason_text: e.target.value })} className="mt-1 block rounded border p-2"/></label>}<button disabled={disabled || !values.override_reason} onClick={onSubmit} className="rounded border border-rose-700 px-3 py-2 text-sm text-rose-800">Override</button></div>;
}

function ReviewQueue({ onBack, canReview }) {
  const [items, setItems] = useState(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const reload = useCallback(() => { setError(''); setItems(null); getAlertQueue().then(setItems).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    let active = true;
    getAlertQueue().then(value => { if (active) setItems(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  async function act(alertId, action) { setBusy(true); setError(''); try { await submitAlertAction(alertId, action); reload(); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  return <section className="space-y-4"><button onClick={onBack} className="text-sm text-blue-800">← Patients</button><h2 className="text-2xl font-bold">Alert review queue</h2>{error && <ErrorMessage>{error}</ErrorMessage>}{items === null && !error ? <Notice>Loading review queue…</Notice> : items?.length ? items.map(item => <article key={item.alert_id} className="rounded-xl border bg-white p-4"><p className="font-semibold">{item.severity} · {item.domain}</p><p className="mt-1">{item.message}</p>{item.last_action && <p className="text-sm font-medium text-blue-900">Latest review action: {item.last_action}</p>}<p className="text-xs text-slate-500">Rule version: {item.rule_version || 'Not available'} · Analysis {item.analysis_id}</p>{canReview && <div className="mt-3 flex gap-2"><button disabled={busy} onClick={() => act(item.alert_id,'ACKNOWLEDGE')} className="rounded border px-3 py-2">Acknowledge</button><button disabled={busy} onClick={() => act(item.alert_id,'REVIEW')} className="rounded border px-3 py-2">Mark reviewed</button></div>}</article>) : <Notice>The review queue is empty.</Notice>}</section>;
}

function SignIn({ onAuthenticated }) {
  const [clinicianId, setClinicianId] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      onAuthenticated(await login(apiKey, clinicianId));
    } catch (requestError) {
      if (requestError.status === 401) setError('Sign-in failed (401): check the API key and clinician ID.');
      else if (requestError.status === 403) setError('Access denied (403): this clinician is not permitted to sign in.');
      else if (requestError.status === 503) setError('Backend unavailable (503): API key validation is not configured.');
      else if (requestError.kind === 'network') setError('Backend unreachable: check the backend connection and try again.');
      else setError(requestError.message || 'Sign-in failed. Try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="mx-auto w-full max-w-md space-y-5 rounded-xl border bg-white p-6 shadow-sm">
    <div><h2 className="text-2xl font-bold">Sign in</h2><p className="mt-1 text-sm text-slate-600">Enter your clinician ID and the shared API key configured for this environment.</p></div>
    <form onSubmit={submit} className="space-y-4">
      <Field label="Clinician ID" status="Required"><input aria-label="Clinician ID" required inputMode="numeric" pattern="[0-9]+" value={clinicianId} onChange={event => setClinicianId(event.target.value)} className="mt-1 w-full rounded border p-2"/></Field>
      <Field label="API key" status="Required"><input aria-label="API key" type="password" autoComplete="current-password" required value={apiKey} onChange={event => setApiKey(event.target.value)} className="mt-1 w-full rounded border p-2"/></Field>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      <button disabled={submitting} className="w-full rounded bg-blue-800 px-4 py-2 font-medium text-white disabled:opacity-50">{submitting ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <Notice tone="amber">The shared API key is a prototype boundary, not production authentication. Do not reuse it as a personal password or expose it in an untrusted environment.</Notice>
  </section>;
}

function App() {
  const [session, setSession] = useState(null);
  const [patient, setPatient] = useState(null);
  const [screen, setScreen] = useState('patients');
  const [restoring, setRestoring] = useState(true);
  const [backendUnreachable, setBackendUnreachable] = useState(false);

  useEffect(() => {
    const expireSession = () => {
      setSession(null);
      setPatient(null);
      setScreen('patients');
    };
    const updateBackendStatus = event => setBackendUnreachable(Boolean(event.detail?.unreachable));
    window.addEventListener('medisafe-auth-expired', expireSession);
    window.addEventListener('medisafe-backend-status', updateBackendStatus);
    restoreSession()
      .then(restoredSession => { if (restoredSession) setSession(restoredSession); })
      .catch(error => { if (error.status === 403) clearStoredCredentials(); })
      .finally(() => setRestoring(false));
    return () => {
      window.removeEventListener('medisafe-auth-expired', expireSession);
      window.removeEventListener('medisafe-backend-status', updateBackendStatus);
    };
  }, []);

  function signOut() {
    logout();
    setSession(null);
    setPatient(null);
    setScreen('patients');
  }

  const roles = session?.roles || [];
  const canRegister = roles.some(role => writableRoles.includes(role));
  const canAnalyze = roles.some(role => ['ADMIN', 'DOCTOR', 'PHARMACIST', 'CLINICAL_REVIEWER'].includes(role));
  const canReview = roles.some(role => ['ADMIN', 'DOCTOR', 'PHARMACIST', 'CLINICAL_REVIEWER'].includes(role));

  if (restoring) return <main className="min-h-screen bg-slate-50 p-8"><Notice>Checking saved sign-in…</Notice></main>;

  return <div className="min-h-screen bg-slate-50 text-slate-900">
    <header className="border-b bg-blue-950 text-white"><div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4">
      <div className="flex items-center gap-3"><Activity className="h-8 w-8 text-blue-200"/><div><h1 className="text-xl font-bold">MediSafe AI</h1><p className="text-xs text-blue-100">Production-oriented clinical decision support prototype</p></div></div>
      {session && <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-sm"><span><UserRound className="mr-1 inline" size={16}/>{session.display_name} · {roles.join(', ')}</span><button onClick={signOut} className="rounded border border-blue-200 px-3 py-1.5 hover:bg-blue-900">Sign out</button></div>}
    </div></header>
    <div role="note" className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm font-medium text-amber-950">Clinical-use disclaimer: This production-oriented clinical decision support prototype is not a substitute for clinician judgment. Verify all information and decisions independently.</div>
    <div role="note" className="border-b border-slate-300 bg-slate-100 px-4 py-2 text-center text-sm text-slate-700">The shared API key is a prototype boundary, not production authentication.</div>
    {backendUnreachable && <div role="alert" className="border-b border-rose-300 bg-rose-50 px-4 py-2 text-center text-sm font-semibold text-rose-900">Backend unreachable. Check that the backend is running and available at the configured API URL.</div>}
    <main className="mx-auto max-w-7xl space-y-6 p-4 md:p-8">
      {!session ? <SignIn onAuthenticated={setSession}/> : <>
        <nav aria-label="Main navigation" className="flex flex-wrap gap-2"><button onClick={() => setScreen('patients')} className={`rounded px-4 py-2 ${screen === 'patients' || screen === 'profile' ? 'bg-blue-800 text-white' : 'border bg-white'}`}>Patients</button><button onClick={() => setScreen('queue')} className={`inline-flex items-center gap-2 rounded px-4 py-2 ${screen === 'queue' ? 'bg-blue-800 text-white' : 'border bg-white'}`}><ClipboardList size={16}/>Review queue</button></nav>
        {screen === 'patients' && <PatientList key={session.clinician_id} canRegister={canRegister} onSelect={selectedPatient => { setPatient(selectedPatient); setScreen('profile'); }}/>}
        {screen === 'profile' && patient && <PatientProfile patient={patient} session={session} onBack={() => setScreen('patients')} onNewPrescription={() => setScreen('prescription')}/>}
        {screen === 'prescription' && patient && <PrescriptionWorkflow patient={patient} canAnalyze={canAnalyze} canReview={roles.some(role => overrideRoles.includes(role))} onBack={() => setScreen('profile')}/>}
        {screen === 'queue' && <ReviewQueue canReview={canReview} onBack={() => setScreen('patients')}/>}
      </>}
    </main>
  </div>;
}

export default App;
