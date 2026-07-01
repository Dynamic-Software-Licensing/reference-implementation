# Development Notes

## Publishing to GitHub

Once approval is granted, recreate the repo and push:

```bash
cd /Users/nooraws/Downloads/Licensing-Initiative/dsl-reference-implementation

# 1. Create the repo (private)
gh repo create Dynamic-Software-Licensing/dsl-reference-implementation --private --description "Interactive reference implementation of the DSL best practices (Chapters 7 & 10)"

# 2. Initialize git (skip if .git/ already exists)
git init
git config user.email "nooraws@amazon.com"
git config user.name "Noor Hassan"

# 3. Add and commit
git add .
git commit -m "Initial release: interactive DSL reference implementation"

# 4. Push
git branch -M main
git remote add origin https://github.com/Dynamic-Software-Licensing/dsl-reference-implementation.git
git push -u origin main
```

If the `.git/` folder already exists from a previous attempt, remove it first:

```bash
rm -rf .git
```

Then run the steps above from step 2.

To make the repo public later:

```bash
gh repo edit Dynamic-Software-Licensing/dsl-reference-implementation --visibility public --accept-visibility-change-consequences
```

## Removing build artifacts for security scanning or upload

The `node_modules/`, `cdk.out/`, `.git/`, and `build/` folders should not be uploaded to security scanners.

To remove them:

```bash
cd /Users/nooraws/Downloads/Licensing-Initiative/dsl-reference-implementation
rm -rf node_modules cdk.out infrastructure/node_modules infrastructure/cdk.out __pycache__ .git .DS_Store workspace-plane/sdk/build
```

This reduces the project from thousands of files to ~34 source files.

## Regenerating dependencies after cleanup

When you need to work with the CDK stack again:

```bash
cd infrastructure
npm install        # Regenerates node_modules/
npx cdk synth     # Regenerates cdk.out/
```

## Running the demo locally (no AWS)

```bash
cd local-mode
pip install -r requirements.txt
python3 mock_control_plane.py 3001
```

In another terminal:

```bash
cd workspace-plane/dashboard
python3 -m http.server 8080
```

Open http://localhost:8080, set Control Plane URL to http://localhost:3001, click Connect.

## Running the demo with AWS backend

```bash
cd infrastructure
npm install
cdk deploy
```

Use the REST API URL from the CDK output in the dashboard's Control Plane URL field.

## AWS Region

All AWS resources deploy to us-east-1 by default.

## Control Plane URL (AWS mode)

```
https://26x24qr1yi.execute-api.us-east-1.amazonaws.com
```

## Security scan notes

- `0.0.0.0` binding was changed to `127.0.0.1` (localhost only)
- JWT payload contains only licensing metadata (non-sensitive)
- innerHTML usage is for internally-generated strings only (no user input)
- Backup/stable files were removed to eliminate duplicate findings
