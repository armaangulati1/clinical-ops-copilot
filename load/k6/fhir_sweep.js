// Single-endpoint saturation sweep for the FHIR patient-fetch path.
//
// This is the script used for the before/after bottleneck comparison. It hits
// only GET /fhir/patient/{id}, the path whose per-request cost is dominated by
// the synthetic patient store in servers/clinical_data/patients.py.
//
// Parametrized by env vars so the driver can run identical config at each VU
// level:
//   VUS       number of virtual users        (default 10)
//   DURATION  steady-state duration          (default 20s)
//   BASE_URL  target base URL                (default http://127.0.0.1:8081)
//
// Run one level directly:
//   k6 run -e VUS=20 -e DURATION=20s load/k6/fhir_sweep.js

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8081';
const VUS = parseInt(__ENV.VUS || '10', 10);
const DURATION = __ENV.DURATION || '20s';

const PATIENT_IDS = ['patient-001', 'patient-002', 'patient-003'];

export const options = {
  scenarios: {
    fhir_steady: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
};

export default function () {
  const id = PATIENT_IDS[Math.floor(Math.random() * PATIENT_IDS.length)];
  const res = http.get(`${BASE_URL}/fhir/patient/${id}`);
  check(res, {
    'status is 200': (r) => r.status === 200,
    'has resourceType': (r) => r.body && r.body.indexOf('Patient') !== -1,
  });
}
