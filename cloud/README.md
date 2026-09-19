# PhotoForge cloud AI proxy

Keeps the NVIDIA API key out of the desktop app.

A key shipped inside PhotoForge is readable with `strings` on the PyInstaller
bundle. Once extracted, anyone can spend your NVIDIA credits and you cannot
revoke it without shipping an update to every user. So the app never holds the
key: it calls this endpoint with the Supabase access token it already has from
signing in, and the key stays in AWS Secrets Manager.

```
desktop app --(Bearer supabase token)--> API Gateway --> Lambda --> NVIDIA NIM
                                                           |
                                                    Secrets Manager
                                                   (the key lives here)
```

Guests can't reach it. "Continue as guest" users have no token, so anonymous
callers are rejected before any NVIDIA call is made.

## One-time setup

You need an AWS account and an NVIDIA API key from
[build.nvidia.com](https://build.nvidia.com) before starting.

**1. Configure the AWS CLI** (already installed):

```sh
aws configure
```

Create an IAM user with programmatic access rather than using your root
account. Give it `AdministratorAccess` for the initial deploy, or scope it down
to CloudFormation, Lambda, API Gateway, IAM, Secrets Manager and DynamoDB.

**2. Install SAM and deploy:**

```sh
brew install aws-sam-cli
cd cloud
sam build
sam deploy --guided \
  --parameter-overrides \
    SupabaseUrl=https://YOUR-PROJECT.supabase.co \
    NimEndpoint=https://ai.api.nvidia.com/v1/genai/VENDOR/MODEL
```

Confirm the `NimEndpoint` path on build.nvidia.com for the model you're
deploying — NIM paths change, which is why it's a parameter and not hardcoded.

**3. Put the NVIDIA key in Secrets Manager.** Note this is a separate step
from the deploy: a key written into `template.yaml` would sit in
CloudFormation's stack history in plaintext forever.

```sh
aws secretsmanager put-secret-value \
  --secret-id photoforge/nvidia-api-key \
  --secret-string '{"api_key":"nvapi-YOUR-KEY"}'
```

**4. Point the app at the deployed endpoint.** `sam deploy` prints
`ApiEndpoint`:

```sh
export PHOTOFORGE_CLOUD_URL="https://xxxx.execute-api.us-east-1.amazonaws.com/v1/edit"
```

## Rotating the key

No redeploy needed — write the new value and let the running functions recycle:

```sh
aws secretsmanager put-secret-value \
  --secret-id photoforge/nvidia-api-key \
  --secret-string '{"api_key":"nvapi-NEW-KEY"}'
```

The function caches the key per warm sandbox, so a rotation takes effect within
a few minutes as Lambda recycles. To cut over immediately, publish a new
function version (`sam deploy`), which starts fresh sandboxes.

## What this costs

Secrets Manager is $0.40/month per secret plus $0.05 per 10k API calls. Lambda
and DynamoDB on-demand are effectively free at this volume — the free tier
covers far more than a photo editor in development will use. API Gateway HTTP
APIs are $1.00 per million requests. Realistically under $1/month until you
have real users; the NVIDIA inference itself will dominate the bill long before
the AWS bill matters.

## Abuse protection

`DailyQuota` (default 25) caps cloud edits per signed-in user per day, counted
in DynamoDB with a TTL so old rows delete themselves. A leaked key is one
failure mode; a signed-in user running a loop is another, and only the quota
guards against the second.

## Security notes

- The Lambda's IAM policy allows `secretsmanager:GetSecretValue` on **one**
  secret ARN. It cannot list secrets or read any other secret in the account.
- Tokens are verified against Supabase's `/auth/v1/user` endpoint rather than
  by checking a JWT signature locally. That costs one round-trip but means this
  function stores no JWT secret of its own, and it honours tokens that were
  revoked server-side — a local signature check would still accept those.
- NVIDIA 401/403 responses are logged but never forwarded to the user; they
  indicate a problem with *our* key, and the detail shouldn't reach clients.
