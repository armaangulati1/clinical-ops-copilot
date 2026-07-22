// Baseline scenario: moderate constant load across the full endpoint mix.
//
// Exercises every non-LLM compute path plus the stubbed agent route at a fixed,
// sustainable VU level so the numbers describe steady-state service behavior
// rather than saturation. Fixtures are read once at init from the repo tree.
//
// Run:
//   k6 run load/k6/baseline.js
//   k6 run -e VUS=10 -e DURATION=30s load/k6/baseline.js

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';
const VUS = parseInt(__ENV.VUS || '10', 10);
const DURATION = __ENV.DURATION || '30s';

// open() is init-context only; paths are relative to this script file.
const X12_278 = open('../../edi/fixtures/submit_ra_case001.278');
const X12_835 = open('../../edi/fixtures/x835/denied_multi_reason.835');
const HL7 = open('../../hl7v2/fixtures/oru_r01_a1c_bmi.hl7');
const PATIENT_IDS = ['patient-001', 'patient-002', 'patient-003'];

export const options = {
  scenarios: {
    mixed_steady: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    http_req_failed: ['rate<0.01'],
  },
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
