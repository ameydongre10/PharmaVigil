# Production Hardening Status - PharmaVigil

## Completed Fixes (Batch 1)

### Core Infrastructure
✅ **conftest.py** - Added isolated test database per run with demo user seeding
✅ **settings.py** - Centralized configuration with environment validation
✅ **Dockerfile** - Non-root user (pharmavigil:1000), multi-stage build
✅ **.dockerignore** - Comprehensive exclusions (tests, outputs, .git, large files)
✅ **requirements.txt** - Pinned versions, moved pytest to requirements-dev.txt

### Security Fixes
✅ **/api/health** - Pure liveness check, never fails due to missing dataset
✅ **/api/ready** - New readiness check with dataset availability
✅ **SSRF Protection** - LLM provider host allowlisting in GenerateRequest
✅ **Authentication** - Added to /api/upload, /api/generate, /api/dataset/reset, /api/sample-data
✅ **Validation Enums** - LLMProviderEnum, UserRoleEnum, ReviewDecisionEnum
✅ **Report ID Sanitization** - Safe filename generation, quoted Content-Disposition headers
✅ **Review Transaction** - Database transaction with state checking (prevent double-review)
✅ **Per-Report Audit** - review_{report_id}.json instead of global review.json overwrite
✅ **CORS from Environment** - settings.CORS_ORIGINS replaces hard-coded list
✅ **Uvicorn Reload** - Environment-driven (off by default, settings.RELOAD)

### Data Persistence
✅ **persist_report()** - Preserves created_at, only updates changed report
✅ **Database Transaction** - record_doctor_verification accepts connection parameter

### Tests Updated
✅ **test_api.py** - All 8 tests passing with authentication
✅ **test_verification_and_upload.py** - Added auth fixtures (analyst_auth, doctor_auth)

## In Progress / Remaining Work

### Test Fixes (HIGH PRIORITY)
🔄 **test_verification_and_upload.py** - 9 more functions need auth headers:
   - test_report_crud_requires_auth_and_preserves_reviewed_reports
   - test_doctor_verification_and_database_audit  
   - test_verification_validation_blocks_unauthorized_access
   - test_excel_dataset_upload_and_analysis
   - test_upload_rejects_file_over_limit
   - test_upload_storage_name_is_not_client_controlled
   - test_upload_validation_errors
   - test_no_silent_fallback_on_missing_dataset
   - test_dataset_persistence_and_reset

### Backend Security & Validation
⚠️ **Password Hashing** - Currently PBKDF2-SHA256 100k iterations, consider:
   - Argon2id (passlib[argon2] or argon2-cffi) - RECOMMENDED
   - bcrypt (passlib[bcrypt]) - Good alternative
   - Current PBKDF2 is acceptable but increase to 600k iterations minimum

⚠️ **LLM Client Hardening** (src/llm_client.py):
   - ✅ Timeouts and retries exist
   - ⚠️ Add better malformed JSON handling with clear fallback message
   - ⚠️ Never log API keys (already done in app.py but verify llm_client.py)
   - ⚠️ Add request/response size limits

⚠️ **Data Loader Edge Cases** (src/data_loader.py):
   - Single-row files (edge case for percentages)
   - All-serious or all-non-serious datasets (division by zero guards)
   - NaN handling in JSON serialization
   - Huge files (add row count limit or streaming)
   - Column count validation (prevent memory exhaustion)

⚠️ **Grounding Validator** (src/grounding_validator.py):
   - Review number extraction for locale formats (commas vs periods)
   - Percentage extraction
   - Date format validation
   - Range handling

### CRUD Operations
❌ **Reports List Pagination** - /api/reports needs:
   - Pagination (offset/limit query params)
   - Filtering (product, status, date_range)
   - Sorting (created_at, updated_at, product_name)
   - Return 200 with pagination metadata

❌ **Report Status Codes**:
   - 201 for POST /api/generate (created)
   - 204 for DELETE (already done)
   - 404 for not found (already done)
   - 409 for conflict (already done)
   - 422 for validation errors

❌ **ETag/Versioning** - Concurrent update protection for PUT /api/reports/{id}

❌ **User Management** (admin endpoints):
   - GET /api/admin/users (list with pagination)
   - PUT /api/admin/users/{id}/role
   - PUT /api/admin/users/{id}/deactivate
   - Requires "admin" role (add to UserRoleEnum)

❌ **Report Features**:
   - POST /api/reports/{id}/duplicate (copy with new dataset/model)
   - GET /api/reports/{id}/history (version history)
   - POST /api/reports/{id}/regenerate-section
   - GET /api/reports/{id}/export (PDF/DOCX in addition to MD/JSON)

### UI Hardening (index.html, docs/index.html)
⚠️ **Two Copies Problem** - Single source of truth:
   - Keep index.html as source
   - Copy to docs/index.html in CI/CD (.github/workflows/pages.yml)
   - Add validation to detect drift

❌ **Frontend Fixes Needed**:
   - XSS protection (use textContent, not innerHTML for API data)
   - Token storage (prefer httpOnly cookie or sessionStorage with short expiry)
   - Token expiry handling (redirect to login on 401)
   - Retry logic for cold-start/503 errors
   - Loading skeletons
   - Empty states
   - Error banners with retry buttons
   - Confirmation dialogs (delete, sign-off)
   - Toast notifications
   - Memory leak prevention (cleanup event listeners)
   - Stale state after logout

❌ **Reports Management Screen**:
   - Table with search/filter/pagination
   - Status badges with color coding
   - Edit and delete actions
   - Bulk actions (if sensible)

❌ **Accessibility**:
   - ARIA labels and roles
   - Keyboard navigation
   - Visible focus indicators
   - WCAG AA color contrast
   - Responsive (mobile 360px+)
   - No console errors

❌ **API URL Configuration**:
   - Make base URL configurable (not hard-coded)
   - Clear CORS error messages

### Rate Limiting & Quotas
❌ **Rate Limiting** (consider slowapi or fastapi-limiter):
   - /api/auth/login: 5 req/min per IP
   - /api/auth/register: 3 req/hour per IP
   - /api/upload: 10 req/hour per user
   - /api/generate: 20 req/hour per user
   - Global: 1000 req/hour per IP

❌ **Upload Quotas**:
   - Per-user file count limit (e.g., 10 active uploads)
   - Per-user storage limit (e.g., 250 MB total)
   - File TTL (cleanup after 7 days)
   - Magic byte validation (verify XLSX/CSV content, not just extension)

### Database & Migrations
❌ **Alembic Migrations** - Replace CREATE TABLE IF NOT EXISTS with versioned migrations

❌ **Database Configuration**:
   - Support DATABASE_URL for managed Postgres/MySQL
   - SQLite WAL mode for better concurrency
   - Busy timeout configuration
   - Connection pooling for production

❌ **Backup Documentation** - Document backup strategy in DEPLOYMENT_GUIDE.md

### Security Headers & Middleware
❌ **Security Headers**:
   - Content-Security-Policy
   - X-Content-Type-Options: nosniff
   - X-Frame-Options: DENY
   - Strict-Transport-Security (when behind HTTPS)
   - X-XSS-Protection: 1; mode=block

❌ **Response Compression** - Enable gzip middleware

❌ **Request Size Limits** - Apply to chunked uploads (not just Content-Length)

### CI/CD & Quality
❌ **GitHub Actions Workflow** (.github/workflows/ci.yml):
   ```yaml
   - ruff check (linting)
   - ruff format --check (formatting)
   - mypy (type checking)
   - pytest --cov --cov-fail-under=85
   - pip-audit (security vulnerabilities)
   - docker build (verify image builds)
   ```

❌ **Pre-commit Hooks** (.pre-commit-config.yaml):
   - ruff
   - mypy
   - trailing-whitespace
   - end-of-file-fixer

❌ **Type Annotations** - Add mypy strict mode and fix any issues

### Documentation Updates
⚠️ **README.md**:
   - Update "120 tests" claim to actual count
   - List test_verification_and_upload.py explicitly
   - Fix "GenAR PADER" branding to "PharmaVigil" consistently
   - Document new /api/ready endpoint
   - Update CORS configuration instructions

⚠️ **.env.example**:
   - Add all new environment variables
   - Document PHARMAVIGIL_SIGNING_KEY requirement for production
   - Add CORS_ORIGINS
   - Add ENVIRONMENT=production
   - Add rate limiting settings

⚠️ **DEPLOYMENT_GUIDE.md**:
   - Persistent disk requirement for Render (outputs/ directory)
   - DATABASE_URL support
   - Environment variable configuration
   - Backup strategy

⚠️ **render.yaml**:
   - Fix service name consistency (pharmavigil vs pader-regulatory-engine)
   - Document persistent disk configuration
   - Add environment variables

### Logging & Monitoring
❌ **Structured Logging**:
   - Request ID middleware
   - Structured JSON logs
   - Never log secrets (API keys, tokens, passwords)
   - Log authentication attempts (success/failure)
   - Log rate limit violations

❌ **Metrics** - Add /metrics endpoint (Prometheus format):
   - Request counts by endpoint
   - Response times
   - Error rates
   - Active reports count
   - Upload sizes

❌ **Exception Handlers**:
   - Consistent error response format
   - No stack traces leaked to clients (only in logs)
   - HTTPException handler
   - General exception handler
   - Validation exception handler

### OpenAPI Documentation
❌ **API Spec Improvements**:
   - Tags for organization
   - Request examples
   - Response models for all endpoints
   - Error response schemas (4xx, 5xx)

## Safety Rules Compliance

All regulatory safety rules (A-H) are preserved:
- ✅ Rule A: Reports start as DRAFT_PENDING_REVIEW
- ✅ Rule B: Automated PASS ≠ HUMAN_APPROVED
- ✅ Rule C: Only explicit human action sets HUMAN_APPROVED
- ✅ Rule D/E: NEEDS_REVISION and REJECTED with timestamped notes
- ✅ Rule F: Simulated approvals tagged is_simulated=true
- ✅ Rule G/H: 8 sections required, expectedness limitations tracked

## Testing Strategy

### Current Status
- ✅ test_api.py: 8/8 passing
- ⚠️ test_verification_and_upload.py: Partially updated, needs completion
- ✅ Baseline: 130/140 tests passing (10 need auth headers)

### Coverage Goals
- Target: 85% minimum
- Add tests for:
  - Edge cases in data_loader.py
  - Malformed JSON from LLM
  - Concurrent review attempts
  - Rate limiting
  - All new CRUD endpoints
  - Admin user management
  - Pagination logic

### Manual Testing Checklist (Before PR)
- [ ] Upload dataset (drag-and-drop and file picker)
- [ ] Generate report with mock LLM
- [ ] Generate report with live LLM (if API key available)
- [ ] Review sign-off flow
- [ ] Edit report metadata
- [ ] Delete draft report
- [ ] Cannot delete reviewed report
- [ ] Login/logout
- [ ] Register new user
- [ ] Token expiry handling
- [ ] Download report (MD, JSON)
- [ ] Reports list with pagination
- [ ] Dataset reset
- [ ] Cold-start retry (if using Render free tier)

## Definition of Done

- [ ] All tests green (140/140)
- [ ] ruff check passes
- [ ] mypy passes (strict mode)
- [ ] Docker image builds
- [ ] Docker container runs as non-root
- [ ] /api/health returns 200
- [ ] /api/ready returns readiness status
- [ ] Manual E2E walkthrough completed
- [ ] README updated
- [ ] .env.example updated
- [ ] DEPLOYMENT_GUIDE.md updated
- [ ] No secrets in code or logs
- [ ] CORS properly configured
- [ ] Rate limiting active
- [ ] All endpoints have proper auth
- [ ] All input validated
- [ ] SQL injection protected (parameterized queries)
- [ ] XSS protected (proper escaping)
- [ ] SSRF protected (allowlisted hosts)
- [ ] No header injection
- [ ] Files cleaned up (TTL)
- [ ] Reviewed reports immutable
- [ ] Audit trail complete

## Risk Assessment

### HIGH RISK (Must Fix)
1. Remaining test failures (blocks verification)
2. Password hashing (security)
3. Frontend XSS vulnerabilities (security)
4. Rate limiting missing (DoS risk)

### MEDIUM RISK (Should Fix)
1. No pagination (scalability)
2. File cleanup missing (disk space)
3. No database migrations (deployment risk)
4. Two frontend copies (maintenance)

### LOW RISK (Nice to Have)
1. Metrics endpoint
2. PDF/DOCX export
3. Report version history
4. Dark mode

## Next Steps

1. Fix remaining 10 test failures in test_verification_and_upload.py
2. Run full test suite to baseline
3. Implement password hashing improvement (Argon2)
4. Add rate limiting
5. Fix frontend XSS and token handling
6. Add pagination to /api/reports
7. Implement file cleanup/TTL
8. Add security headers
9. Create CI/CD workflow
10. Update all documentation
11. Manual E2E testing
12. Create final CHANGELOG for PR

## Time Estimate

- Remaining test fixes: 30 minutes
- Password & rate limiting: 1 hour
- Frontend hardening: 2 hours
- CRUD improvements: 1.5 hours
- CI/CD & docs: 1 hour
- Manual testing: 30 minutes
- **Total: ~6.5 hours**

## Notes

- All changes maintain backward compatibility where possible
- No regulatory safety rules weakened
- Authentication added without breaking existing flows (demo users still work)
- Database schema unchanged (can add migrations later)
- Focus on security first, features second
