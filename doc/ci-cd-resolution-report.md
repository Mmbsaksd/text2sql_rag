# CI/CD Resolution Report

## Purpose

This document explains, step by step, how the CI/CD and AWS Lambda deployment issues were diagnosed and fixed in this repository.

It is written as a learning report, not just a change log. The goal is to show:

- what was checked first
- what failed
- how each failure was interpreted
- what was changed
- how each fix was verified
- how to think through similar deployment issues in the future

Important note:
This report explains the decision process and debugging workflow in a practical way. It does not expose hidden internal chain-of-thought, but it does give the useful engineering reasoning, commands, and lessons.

## Starting Situation

At the beginning:

- The repository had new CI/CD files and Lambda-related files that were not fully validated.
- The deploy path targeted AWS Lambda using container images.
- GitHub Actions secrets were partially configured.
- The user wanted to know whether the repo was safe to push for CI/CD deployment.

Files directly involved:

- `.github/workflows/deploy.yml`
- `.github/workflows/test.yml`
- `Dockerfile.lambda`
- `lambda_handler.py`
- `app/main.py`
- multiple service files under `app/services/`

## High-Level Debugging Strategy

The work followed this order:

1. Inspect the repository state and relevant files.
2. Validate the local code quality path first.
3. Validate Docker and Lambda wiring next.
4. Push only after local checks were clean enough.
5. Watch GitHub Actions live.
6. Fix each remote failure one by one.
7. Validate the real deployed Lambda URL in AWS.
8. Harden the workflow so the same failures do not happen again.

This order matters.

Why?

- If the code itself is broken, deployment debugging is wasted effort.
- If the workflow is broken, local code health is not enough.
- If AWS permissions or infrastructure are missing, even a perfect workflow will fail.

## Step 1: Inspect the Repo and Existing Files

First checks:

```powershell
git status --short
git remote -v
rg --files .github Dockerfile.lambda lambda_handler.py
```

What this established:

- CI/CD files existed but were uncommitted.
- `Dockerfile.lambda.base` was expected by the user context, but it did not actually exist in the repo at first.
- The deployment setup needed file-level verification before pushing.

## Step 2: Read the Actual Workflow and Runtime Files

Files inspected:

- `.github/workflows/deploy.yml`
- `.github/workflows/test.yml`
- `Dockerfile.lambda`
- `lambda_handler.py`
- `app/main.py`
- `app/config.py`

Why this step was important:

- CI/CD failures usually come from mismatches between workflow assumptions and real app behavior.
- The workflow was testing `/health` and `/info`, so the app had to expose those routes correctly.
- The Lambda handler had to be compatible with Lambda Function URLs.

## Step 3: Run Local Validation Before Pushing

Commands used:

```powershell
.venv\Scripts\python.exe -m ruff check app lambda_handler.py
.venv\Scripts\python.exe -m black --check app lambda_handler.py
.venv\Scripts\python.exe -m compileall app lambda_handler.py
```

Results:

- `compileall` passed, so syntax was broadly fine.
- `ruff` failed with many issues.
- `black --check` failed and wanted to reformat many files.

Important lesson:

- A deployment workflow is not "ready" if the validation workflow will fail immediately.
- Fix local gates first, because GitHub Actions will only repeat the same failures remotely.

## Step 4: Find the First Real Code Bug

One of the most important real bugs was in:

- `app/services/rag_service.py`

Problem:

- a variable named `headings` was referenced before assignment in one branch

Why this mattered:

- This was not just style.
- It could cause runtime errors when building context from retrieved document chunks.

Fix:

- Changed the non-string branch to use `headings_json` instead of the undefined `headings`.

## Step 5: Clean Up Code Quality Issues

After the initial scan, the codebase had:

- unused imports
- bad exception style
- import-order issues
- formatting inconsistencies

Commands used:

```powershell
.venv\Scripts\python.exe -m ruff check app lambda_handler.py --fix
.venv\Scripts\python.exe -m black app lambda_handler.py
.venv\Scripts\python.exe -m ruff check app lambda_handler.py
.venv\Scripts\python.exe -m black --check app lambda_handler.py
```

Examples of fixes made:

- removed unused imports
- replaced a bare `except:` with safer handling
- corrected service messages and config references
- fixed code formatting

Why this mattered:

- `test.yml` explicitly runs `ruff` and `black`
- until both pass, the PR/test pipeline is not healthy

## Step 6: Fix Lambda Handler and Runtime Assumptions

File:

- `lambda_handler.py`

Original problem areas:

- handler behavior was too tightly tied to a `/prod` base path assumption
- that assumption fit API Gateway, but the repo and documentation were using Lambda Function URLs
- Lambda Function URLs do not use `/prod`

Fixes made:

- changed the handler to load lazily
- created the Mangum adapter lazily
- removed the incorrect `/prod` assumption
- kept `/tmp` directory setup for Lambda storage

Why this mattered:

- wrong base path configuration can break docs routes and request handling
- Function URL requests should hit `/health`, not `/prod/health`

## Step 7: Build Docker Path Correctly

Early finding:

- `Dockerfile.lambda.base` did not exist
- but the workflow referenced it

That meant:

- GitHub Actions would fail as soon as it tried to build the base image

Fix:

- created `Dockerfile.lambda.base`

Purpose of that file:

- install shared native dependencies once
- reduce repeated cost and runtime for Lambda image builds

Also fixed:

- `Dockerfile.lambda` originally referenced a hardcoded ECR image
- changed it to use a configurable build argument for the base image

Important Docker command pattern used:

```powershell
docker build --platform linux/amd64 -f Dockerfile.lambda.base -t lambda-python-deps:test .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=lambda-python-deps:test -f Dockerfile.lambda -t rag-lambda:test .
```

## Step 8: Rewrite the GitHub Actions Workflows to Match Reality

### Changes to `test.yml`

Added/kept:

- Python setup
- dependency install
- `ruff`
- `black --check`
- optional pytest
- Docker base image build
- Docker Lambda image build

Why:

- the workflow should validate both code quality and container buildability

### Changes to `deploy.yml`

The deploy workflow was redesigned to:

- validate secrets before doing expensive work
- run the same validation path used by CI
- ensure ECR repositories exist
- build and push the base image
- build and push the application image
- create the Lambda function if it does not exist
- update Lambda code if it already exists
- update environment variables
- create or reuse Lambda Function URL
- smoke test `/health` and `/info`

This is the biggest architecture improvement from the session.

## Step 9: Push and Watch GitHub Actions Live

Commits created during the process:

```text
928c034 Fix Lambda CI/CD deployment flow
004dd93 Fix Docker base image arg resolution
324a54f Bootstrap Lambda function URL in deploy workflow
5a0a19c Remove reserved Lambda env key
2a7d1ec Wait for Lambda code updates before config
8b0a679 Harden Function URL smoke tests
```

Command used:

```powershell
git push origin main
```

After each push, GitHub Actions was checked with:

```powershell
gh run list --limit 6
gh run view <run-id>
gh run view <run-id> --log-failed
gh run watch <run-id> --exit-status
```

Why this matters:

- good CI/CD debugging is iterative
- you do not guess all fixes in advance
- you push a fix, observe the next failure, and remove blockers one by one

## Step 10: First Remote Failure - Docker Build Arg Resolution

Failure:

- Docker build failed because `BASE_IMAGE` was blank in `Dockerfile.lambda`

Root cause:

- `ARG BASE_IMAGE=...` was placed too late for the `FROM ${BASE_IMAGE}` line

Fix:

- moved the `ARG BASE_IMAGE=...` definition before it was needed

Lesson:

- Docker `ARG` scope matters
- if a variable is used in `FROM`, it must be declared early enough

## Step 11: Second Remote Failure - Missing `API_GATEWAY_URL`

Failure:

- deploy workflow stopped because `API_GATEWAY_URL` secret was empty

Investigation showed:

- all other required secrets were present
- the real deployment target was a Lambda Function URL, not API Gateway

Fix:

- removed the hard requirement on `API_GATEWAY_URL`
- taught the workflow to create or discover the Lambda Function URL itself

Lesson:

- do not depend on secrets for values that the workflow can safely discover from AWS
- fewer manual secrets means fewer deployment failures

## Step 12: Third Remote Failure - No Lambda Function Existed

AWS inspection commands:

```powershell
aws configure list
aws lambda list-functions --max-items 20 --query "Functions[].FunctionName" --output text
aws iam get-role --role-name rag-lambda-execution-role
aws ecr describe-repositories --repository-names rag-text-to-sql-server lambda-python-deps
```

What was found:

- IAM role existed: `rag-lambda-execution-role`
- no Lambda functions existed yet
- ECR repository needed first-time bootstrap handling

Fix:

- updated the workflow so it could:
  - create ECR repos if missing
  - create the Lambda function on first deploy
  - update it on later deploys

Lesson:

- deployment pipelines must handle both:
  - first deployment
  - later incremental deployments

## Step 13: Fourth Remote Failure - Reserved Lambda Environment Variable

Failure:

- Lambda rejected environment update because `AWS_REGION` is reserved

Error meaning:

- some environment keys are managed by Lambda itself and cannot be overridden

Fix:

- removed `AWS_REGION` from the environment payload

Lesson:

- when Lambda says a key is reserved, do not fight it
- remove it from the workflow instead of retrying the same payload

## Step 14: Fifth Remote Failure - Update-In-Progress Race Condition

Failure:

- `UpdateFunctionConfiguration` ran while Lambda code update was still in progress

Root cause:

- the workflow waited for the wrong Lambda state after image update

Fix:

- after `update-function-code`, wait for:
  - `aws lambda wait function-updated`
- after `create-function`, wait for:
  - `aws lambda wait function-active`

Lesson:

- different AWS operations require different wait states
- using the wrong waiter causes race conditions

## Step 15: Sixth Remote Failure - Function URL Returned 403

Observed deploy failure:

```text
curl: (22) The requested URL returned error: 403
```

AWS checks used:

```powershell
aws lambda get-function-url-config --function-name rag-text-to-sql-server
aws lambda get-policy --function-name rag-text-to-sql-server
```

What was found:

- Function URL existed
- `AuthType` was `NONE`
- policy had only one permission:
  - `lambda:InvokeFunctionUrl`

But AWS now requires two statements for public Function URLs.

The missing one was:

- `lambda:InvokeFunction`
- with `InvokedViaFunctionUrl=true`

Direct repair command used:

```powershell
aws lambda add-permission --function-name rag-text-to-sql-server --statement-id FunctionURLAllowPublicInvoke --action lambda:InvokeFunction --principal "*" --invoked-via-function-url
```

After this, the policy contained both required statements.

Lesson:

- a 403 at the Function URL level is often not an app bug
- it may be missing Lambda resource policy permissions

## Step 16: Verify the Real URL Works

Test command:

```powershell
curl.exe -i --max-time 120 https://ckjaitknndevz3gmru326ofccm0vfexy.lambda-url.us-east-1.on.aws/health
```

Result:

- HTTP `200 OK`
- healthy JSON response
- services initialized successfully

The response proved:

- the deployed app is running
- Lambda Function URL is public and working
- core dependencies and service initialization succeeded

## Step 17: Final Workflow Hardening

Even though the production URL was fixed, the workflow also needed to be future-safe.

Final hardening changes:

- always try to apply both Function URL permissions
- use the correct permission model:
  - `lambda:InvokeFunctionUrl` with `--function-url-auth-type NONE`
  - `lambda:InvokeFunction` with `--invoked-via-function-url`
- add smoke-test retry logic
- add longer timeouts for cold starts
- wait before testing

Why:

- a Lambda can be healthy but still slow during cold start
- a workflow should handle expected platform behavior

## Step 18: Final Validation Status

Final GitHub Actions runs:

```text
24352792180  Deploy to AWS Lambda  success
24352792163  Test CI               success
```

Final repo status:

```powershell
git status --short
```

Result:

- clean working tree

## Important Commands Used and Why

### Local validation

```powershell
.venv\Scripts\python.exe -m ruff check app lambda_handler.py
.venv\Scripts\python.exe -m black --check app lambda_handler.py
.venv\Scripts\python.exe -m compileall app lambda_handler.py
```

Purpose:

- verify code quality and syntax before pushing

### Auto-fix and formatting

```powershell
.venv\Scripts\python.exe -m ruff check app lambda_handler.py --fix
.venv\Scripts\python.exe -m black app lambda_handler.py
```

Purpose:

- reduce manual cleanup effort

### Docker validation

```powershell
docker build --platform linux/amd64 -f Dockerfile.lambda.base -t lambda-python-deps:test .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=lambda-python-deps:test -f Dockerfile.lambda -t rag-lambda:test .
```

Purpose:

- verify the Lambda container images can build

### Git operations

```powershell
git add ...
git commit -m "..."
git push origin main
```

Purpose:

- publish fixes and trigger GitHub Actions

### GitHub Actions inspection

```powershell
gh run list --limit 6
gh run view <run-id>
gh run view <run-id> --log-failed
gh run watch <run-id> --exit-status
```

Purpose:

- observe exactly where CI/CD fails

### AWS inspection

```powershell
aws configure list
aws lambda list-functions --max-items 20 --query "Functions[].FunctionName" --output text
aws iam get-role --role-name rag-lambda-execution-role
aws ecr describe-repositories --repository-names rag-text-to-sql-server lambda-python-deps
aws lambda get-function-url-config --function-name rag-text-to-sql-server
aws lambda get-policy --function-name rag-text-to-sql-server
aws logs tail /aws/lambda/rag-text-to-sql-server --since 10m --format short
```

Purpose:

- verify AWS resources and read runtime behavior

### AWS repair command

```powershell
aws lambda add-permission --function-name rag-text-to-sql-server --statement-id FunctionURLAllowPublicInvoke --action lambda:InvokeFunction --principal "*" --invoked-via-function-url
```

Purpose:

- fix the Function URL 403 by adding the missing permission

## Files Created or Significantly Changed

Main workflow and deployment files:

- `.github/workflows/deploy.yml`
- `.github/workflows/test.yml`
- `Dockerfile.lambda`
- `Dockerfile.lambda.base`
- `lambda_handler.py`

Important application files touched during cleanup:

- `app/main.py`
- `app/utils.py`
- `app/services/cache_service.py`
- `app/services/rag_service.py`
- `app/services/s3_storage.py`
- `app/services/sql_service.py`
- other service files reformatted by `black`

## How to Think About Problems Like This in the Future

Use this mindset:

### 1. Separate the problem layers

Ask:

- is this a code problem?
- a workflow problem?
- a container problem?
- an AWS infrastructure problem?
- a permissions problem?

Do not mix all layers at once.

### 2. Make the smallest strong verification first

Examples:

- run `ruff` and `black`
- run `compileall`
- inspect the real workflow
- test the real URL directly

### 3. Read the exact failed step

Do not guess from the top-level red mark.

Instead:

- open the failed step
- read the exact error
- fix that exact blocker

### 4. Distinguish fast failures from slow failures

- `403` often means permissions or access policy
- `timeout` often means cold start, long initialization, or hanging code
- Docker `FROM` failures often mean image or build-arg problems
- Lambda `ResourceConflictException` often means you touched config before code update settled

### 5. Make workflows self-healing where safe

Good examples:

- create repos if missing
- create function if missing
- discover URL instead of requiring a secret
- add retries for cold starts

### 6. Re-test the real system after every important fix

Not just local checks.

Also test:

- the GitHub Actions rerun
- the AWS Lambda Function URL
- the CloudWatch logs if needed

## Final Outcome

Final result:

- local validation passes
- CI passes
- deployment workflow passes
- Lambda container builds
- Lambda function exists
- environment variables apply correctly
- Function URL permissions are correct
- `/health` returns `200 OK`

In short:

- the repository is now in a healthy deployable state
- the deployment path is much stronger than at the beginning
- the workflow now handles both first-time setup and repeat deployments

## Suggested Next Improvements

These are optional but useful:

1. Add a dedicated staging Lambda environment.
2. Add a separate smoke test for `/info` and `/health` with structured output checking.
3. Add workflow artifact uploads for failed logs.
4. Upgrade GitHub Actions versions when Node 24-compatible releases are available.
5. Add explicit tests for Function URL policy creation.
6. Add one short architecture README for:
   - local run
   - CI validation
   - deploy flow
   - AWS resources involved
