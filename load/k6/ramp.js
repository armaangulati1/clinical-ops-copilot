// Ramp scenario: drive the mixed workload up through increasing VU levels to
// locate the saturation knee. Uses the ramping-vus executor so a single run
// walks the full curve; per-stage latency is visible in the time series and the
// end-of-run summary reports the aggregate p95/p99 across the ramp.
//
// For clean per-level throughput/p95/p99 tables, prefer the discrete sweep in
// load/run_load.sh (which invokes fhir_sweep.js at fixed VU counts). This ramp
// is the qualitative "where does it fall over" view.
//
// Run:
//   k6 run load/k6/ramp.js

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';

const X12_278 = open('../../edi/fixtures/submit_ra_case001.278');
const X12_835 = open('../../edi/fixtures/x835/denied_multi_reason.835');
const HL7 = open('../../hl7v2/fixtures/oru_r01_a1c_bmi.hl7');
const PATIENT_IDS = ['patient-001', 'patient-002', 'patient-003'];

export const options = {
  scenarios: {
    mixed_ramp: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '15s', target: 10 },
        { duration: '15s', target: 20 },
        { duration: '15s', target: 40 },
        { duration: '15s', target: 80 },
        { duration: '15s', target: 120 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const r278 = http.post(`${BASE_URL}/parse/x12/278`, X12_278, {
    headers: { 'Content-Type': 'text/plain' },
  });
  check(r278, { '278 ok': (r) => r.status === 200 });

  const r835 = http.post(`${BASE_URL}/parse/x12/835`, X12_835, {
    headers: { 'Content-Type': 'text/plain' },
  });
  check(r835, { '835 ok': (r) => r.status === 200 });

  const rhl7 = http.post(`${BASE_URL}/parse/hl7v2`, HL7, {
    headers: { 'Content-Type': 'text/plain' },
  });
  check(rhl7, { 'hl7 ok': (r) => r.status === 200 });

  const id = PATIENT_IDS[Math.floor(Math.random() * PATIENT_IDS.length)];
  const rfhir = http.get(`${BASE_URL}/fhir/patient/${id}`);
  check(rfhir, { 'fhir ok': (r) => r.status === 200 });

  const rdecide = http.post(`${BASE_URL}/agent/decide`);
  check(rdecide, { 'decide ok': (r) => r.status === 200 });
}
