// k6 smoke: `k6 run -e API=http://localhost:8000 scripts/load/smoke.js`
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 10,
  duration: "30s",
  thresholds: { http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<500"] },
};

const API = __ENV.API || "http://localhost:8000";

export default function () {
  check(http.get(`${API}/health`), { "health 200": (r) => r.status === 200 });
  check(http.get(`${API}/api/config`), { "config 200": (r) => r.status === 200 });
  check(http.get(`${API}/api/v1/billing/plans`), {
    "plans 200": (r) => r.status === 200,
    "rate header": (r) => r.headers["X-Ratelimit-Remaining"] !== undefined,
  });
  sleep(1);
}
