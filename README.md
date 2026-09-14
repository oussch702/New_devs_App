# Property Revenue Dashboard — debugging submission

Focused fixes to the supplied React/FastAPI/PostgreSQL/Redis application. The existing architecture and dashboard layout are retained.

## Run locally

```bash
docker compose up --build -d
```

Open the dashboard at http://localhost:3000 and API documentation at http://localhost:8000/docs. If port 3000 is occupied:

```bash
FRONTEND_PORT=3001 docker compose up --build -d
```

Then open http://localhost:3001. The database is initialized from the original schema and seed files. No Supabase account or external service credentials are required for the supplied challenge accounts.

| Account | Email | Password |
| --- | --- | --- |
| Sunset Properties | `sunset@propertyflow.com` | `client_a_2024` |
| Ocean Rentals | `ocean@propertyflow.com` | `client_b_2024` |

The dashboard opens on March 2024, the period covered by the supplied data. Select a property, month, or full year to change the report.

## Findings and fixes

| Finding | Root cause | Fix |
| --- | --- | --- |
| Another client's revenue appeared | Redis key included only property ID; both clients own `prop-001` | Authorize the property against the authenticated tenant before cache access; use versioned tenant/property/period/timezone keys and validate cached context |
| Incorrect or fabricated totals | Database pool referenced missing settings, used a synchronous pool with an async engine, and exposed a coroutine where callers expected a context manager; exceptions returned hardcoded revenue | Use `DATABASE_URL`, one shared async pool and correctly managed sessions; query the real data and return 503 on database failure |
| Monthly reports did not represent a month | Monthly function was a placeholder and the dashboard called an all-time summary | Wire month/year filters through the UI, API, cache, and actual database query |
| Boundary booking could be assigned to the wrong month | Calendar boundaries were naive and did not use the property's timezone | Convert each local start/end boundary to a PostgreSQL `timestamptz`; use an inclusive start and exclusive end |
| Financial precision was not preserved end to end | API converted decimal totals into binary floats, then the frontend performed float rounding | Sum PostgreSQL NUMERIC values, round once with Decimal, serialize decimal strings, and format strings without float conversion |
| Currency could be mislabeled or combined | Summary hardcoded USD without grouping reservation currencies | Return a separate total for each currency; do not perform implicit currency conversion |
| Tenant identity could fall back to another client | Resolver chose tenant by email and defaulted to Sunset; challenge fallback accepted unsigned/mock tokens and legacy logins without password verification | Resolve verified server-controlled claims, reject missing tenant, enforce supplied credential pairs, reject invalid/expired tokens, and bound auth caching by token expiry |
| Login/account switching could fail or show stale data | Local auth adapter returned incompatible shapes; pending requests and global bootstrap data could outlive the active session | Match existing auth interfaces, clear session data promptly, and discard results from superseded sessions/selections |
| Refresh could lose a valid login | Storage migration preserved legacy Supabase keys but deleted the local adapter's `base360-auth-token` | Preserve the actual session key in both migration paths and cover version changes with regression tests |
| Dashboard exposed the wrong property names | Hardcoded shared property list | Fetch the signed-in tenant's properties from the backend; Ocean sees Mountain Lodge Beta |

Redis failure now bypasses caching and queries PostgreSQL. Cache versioning ignores old unsafe entries without flushing unrelated data. Database errors never produce synthetic financial results. The fabricated growth indicator was removed because no supporting calculation existed.

## Reporting rules and expected results

- Recognize the full reservation amount in the property-local **check-in** month; do not prorate across the stay.
- Aggregate the original three-decimal amounts before rounding; use `ROUND_HALF_UP` to two decimal places for these reports.
- Report currencies independently. There is no exchange-rate source in this assignment.
- An owned property with no reservations returns `0.00` USD and zero bookings, following the fixture's default currency.
- A foreign or nonexistent property returns 404. An invalid token returns 401; an authenticated identity without a trusted tenant returns 403.

March 2024 fixture oracle:

| Client | Property | Revenue (USD) | Bookings |
| --- | --- | ---: | ---: |
| Sunset | Beach House Alpha (`prop-001`) | 2,250.00 | 4 |
| Sunset | City Apartment Downtown (`prop-002`) | 4,975.50 | 4 |
| Sunset | Country Villa Estate (`prop-003`) | 6,100.50 | 2 |
| **Sunset total** | | **13,326.00** | **10** |
| Ocean | Mountain Lodge Beta (`prop-001`) | 0.00 | 0 |
| Ocean | Lakeside Cottage (`prop-004`) | 1,776.50 | 4 |
| Ocean | Urban Loft Modern (`prop-005`) | 3,256.00 | 3 |
| **Ocean total** | | **5,032.50** | **7** |

The Paris booking at `2024-02-29 23:30 UTC` is March 1 at 00:30 locally, so its 1,250.00 belongs in March. All seeded bookings fall in local March; February totals are zero and the seeded 2024 annual totals equal March totals. The fixture amounts `333.333 + 333.333 + 333.334` total exactly `1000.000`, reported as `1000.00`.

## API changes

`GET /api/v1/dashboard/properties` returns `{ "properties": [{ "id", "name", "timezone" }] }` scoped to the verified tenant.

`GET /api/v1/dashboard/summary?property_id=prop-001&year=2024&month=3` returns:

```json
{
  "property_id": "prop-001",
  "timezone": "Europe/Paris",
  "year": 2024,
  "month": 3,
  "reservations_count": 4,
  "total_revenue": "2250.00",
  "currency": "USD",
  "totals_by_currency": [
    { "currency": "USD", "total_revenue": "2250.00", "reservations_count": 4 }
  ]
}
```

Year alone selects the local calendar year. Omitting both period parameters retains all-time reporting. Month without year, months outside 1–12, and years outside 1–9998 return 422. Monetary fields are now strings; the included frontend is updated accordingly. For multiple currencies, the legacy top-level amount/currency are null and `totals_by_currency` carries each total. Redis entries expire after five minutes.

## Verification

Run all backend tests against the running local stack:

```bash
docker compose exec -T backend env RUN_INTEGRATION_TESTS=1 python -m unittest discover -s tests -v
```

Integration tests use the real HTTP API, PostgreSQL schema/seed, and Redis. They insert uniquely named test properties/reservations and remove those rows after each test. Authentication and service tests also cover invalid tokens, cache payload corruption, service failures, and pool lifecycle without changing running services.

Run frontend regression tests with Node 22.13 or newer; no npm installation is needed for these tests:

```bash
node --test frontend/tests/*.test.mjs
```

Verify the production build:

```bash
docker compose build frontend
```

The dedicated **Dashboard regressions** GitHub Actions workflow performs the frontend tests, production Docker build, and full backend suite on pushes and pull requests to main. The original pre-commit workflow remains available.

The baseline integration run failed 34 assertions across 12 tests. The fixes are checked against those same scenarios, including cache request order, Paris/New York DST boundaries, December/January rollover, exact cents, negative adjustments, multiple currencies, and forbidden properties.

Verified locally on September 14, 2026:

- **34 backend tests passed:** 12 real-database integration tests, 10 authentication tests, and 12 revenue/cache/pool tests.
- **14 frontend tests passed:** authentication response shapes, session races, exact amount formatting, tenant/period caching, and storage migration preservation.
- The production frontend Docker build passed.
- Chrome browser checks passed for both logins, authorized property names, exact totals, month/year changes, delayed responses, logout/account switching, refresh, error/retry recovery, and a 390px mobile viewport; no page exceptions occurred.
- Separate real connection-refusal checks confirmed Redis failure returns the actual database total and PostgreSQL failure returns 503.

For the required recording, follow [LOOM_WALKTHROUGH.md](LOOM_WALKTHROUGH.md).
