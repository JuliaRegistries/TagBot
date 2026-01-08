# TODO: Upgrade to Serverless v4

Currently using Serverless v3 because v4 requires AWS credentials even for `serverless package` validation in CI.

## Why v4?

- v3 is deprecated and will eventually be unsupported
- v4 has better performance and features
- Required for newer serverless plugins

## AWS Setup Required for v4

### 1. Create IAM Identity Provider for GitHub OIDC

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

### 2. Create IAM Role with Trust Policy

Create a role (e.g., `TagBot-CI-Role`) with this trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:JuliaRegistries/TagBot:*"
        }
      }
    }
  ]
}
```

Replace `ACCOUNT_ID` with your AWS account ID.

### 3. Attach Minimal Permissions

For CI packaging validation, the role needs minimal permissions. A basic read-only policy should suffice since CloudFormation intrinsic functions (`${AWS::Region}`, `${AWS::AccountId}`) are resolved at deploy time, not package time.

### 4. Add Repository Secrets

Add to GitHub repository secrets:
- `AWS_ROLE_ARN`: `arn:aws:iam::ACCOUNT_ID:role/TagBot-CI-Role`
- `SERVERLESS_ACCESS_KEY`: Get from https://app.serverless.com → Account Settings → Access Keys

### 5. Update package.json

Remove the pinned serverless v3:

```json
"devDependencies": {
  "serverless-domain-manager": "^8.0.0",
  "serverless-wsgi": "^3.1.0"
}
```

### 6. Update CI Workflow

The workflow at `.github/workflows/web.yml` already has the OIDC setup prepared (in git history). Restore it or use:

```yaml
permissions:
  id-token: write
  contents: read
jobs:
  check:
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1
```

## References

- [GitHub OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [aws-actions/configure-aws-credentials](https://github.com/aws-actions/configure-aws-credentials)
- [Serverless v4 Credentials](https://www.serverless.com/framework/docs/providers/aws/guide/credentials)
