# Deploying to Azure

This guide puts the resume evidence matcher on Azure Container Apps with a managed Postgres database, for someone who hasn't used Azure before. Every command is meant to be copied as written, after setting the variables in step 1. The commands are for bash (Linux, macOS, or WSL and Git Bash on Windows).

The template is `infra/azure/main.bicep`. It was checked with the Bicep CLI (`bicep build` and `bicep lint`, which check every resource property against Azure's schemas) but hasn't been deployed by the project yet, so treat the first deploy as a test and read the output of each step.

## What gets created

| Resource | What it is for |
| --- | --- |
| Log Analytics workspace | Keeps the logs of every container for 30 days. |
| Container Apps environment | Runs the containers, on the Consumption plan. |
| Postgres Flexible Server | The database, with one database named `matcher`. It only accepts encrypted (TLS) connections, and Azure encrypts its storage and backups at rest. Backups are kept for 7 days. |
| `<prefix>-api` container app | The API, with ClamAV next to it as a second container. Every upload is scanned before it is read. |
| `<prefix>-ui` container app | The Streamlit screen. It calls the API over HTTPS. |
| `<prefix>-migrate` job | Runs the database migrations when you start it. |

Both apps have public HTTPS addresses. A request over plain HTTP is redirected to HTTPS. Each app runs exactly one copy (replica), because the rate limits are counted in the API's memory and the screen keeps each visitor's session in its own memory. Secrets (the database URL with its password, the Anthropic key and an optional registry token) are stored as Container App secrets and reach the containers only as environment variables that point at them.

## Before you start

You need:

1. An Azure subscription where you can create resources.
2. The Azure CLI, version 2.79 or newer: see https://learn.microsoft.com/cli/azure/install-azure-cli. Check with `az version`.
3. The images on the GitHub Container Registry. Push a tag such as `v1.0.0` to your GitHub repository and the release workflow (`.github/workflows/release.yml`) builds and pushes `ghcr.io/<owner>/resume-evidence-matcher-api` and `-ui`. New packages on ghcr.io are private. Either make both public (on GitHub: your profile, Packages, the package, Package settings, Change visibility), or create a token with the `read:packages` scope and pass it in step 3 as shown there.

## 1. Sign in and choose names

```bash
az login
az account set --subscription "<subscription name or id>"
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.DBforPostgreSQL --wait

RG=resume-matcher        # resource group name
LOCATION=eastus          # any region with Container Apps and Postgres Flexible Server
PREFIX=rem               # 2 to 12 lowercase letters or digits, used in every name
OWNER=your-github-user   # your GitHub user or organization, in lowercase
TAG=v1.0.0               # the release to deploy
```

## 2. Create the resource group

```bash
az group create --name "$RG" --location "$LOCATION"
```

## 3. Create the database and the migration job

The first deploy runs in two passes. This first one creates everything except the two apps, because the API refuses to start in production while the database has migrations pending.

Choose a Postgres administrator password: 12 to 128 characters, with at least three of uppercase letters, lowercase letters, digits and symbols. `read -s` keeps it off the screen and out of your shell history.

```bash
read -rs -p "Postgres admin password: " POSTGRES_ADMIN_PASSWORD; echo

az deployment group create \
  --resource-group "$RG" \
  --name matcher \
  --template-file infra/azure/main.bicep \
  --parameters infra/azure/main.parameters.example.json \
  --parameters namePrefix="$PREFIX" \
    apiImage="ghcr.io/$OWNER/resume-evidence-matcher-api:$TAG" \
    uiImage="ghcr.io/$OWNER/resume-evidence-matcher-ui:$TAG" \
    postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
    deployApps=false
```

This takes about 10 minutes, most of it for Postgres. If you kept the images private, add these two parameters to the deploy commands in steps 3 and 5 (a token is safer than your password):

```bash
read -rs -p "GitHub token with read:packages: " GHCR_TOKEN; echo
# then add to the --parameters line:
#   registryUsername="$OWNER" registryPassword="$GHCR_TOKEN"
```

For matching by meaning, deploy the `-ml` image instead (`apiImage="ghcr.io/$OWNER/resume-evidence-matcher-api:$TAG-ml"`) with more memory for the API: `apiCpu=1 apiMemory=2Gi`. The app's total must stay a valid Consumption size, and 1 vCPU and 2 GiB for the API plus the ClamAV defaults (1.5 vCPU and 3 GiB) is 2.5 vCPU and 5 GiB, which is one. Its first start downloads the two models (about 180 MB) from Hugging Face.

## 4. Run the migrations once

```bash
az containerapp job start --name "$PREFIX-migrate" --resource-group "$RG"

# Repeat until the newest run shows Succeeded (usually within a minute or two):
az containerapp job execution list --name "$PREFIX-migrate" --resource-group "$RG" \
  --query "[].{run:name, status:properties.status, started:properties.startTime}" --output table

# What it printed:
az containerapp job logs show --name "$PREFIX-migrate" --resource-group "$RG" \
  --container migrate --format text
```

The job runs `alembic upgrade head` and then prints "The database is at revision 0001, the newest." If it fails, its log says why. A wrong password or a database that isn't reachable shows up there.

## 5. Create the apps

The same command as step 3, without `deployApps=false`:

```bash
az deployment group create \
  --resource-group "$RG" \
  --name matcher \
  --template-file infra/azure/main.bicep \
  --parameters infra/azure/main.parameters.example.json \
  --parameters namePrefix="$PREFIX" \
    apiImage="ghcr.io/$OWNER/resume-evidence-matcher-api:$TAG" \
    uiImage="ghcr.io/$OWNER/resume-evidence-matcher-ui:$TAG" \
    postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD"
```

Then get the addresses:

```bash
az deployment group show --resource-group "$RG" --name matcher \
  --query "properties.outputs.{screen:uiUrl.value, api:apiUrl.value}" --output table
```

ClamAV loads its signatures for a minute or two after each start, and the API reports itself ready only once both the database and ClamAV answer. Check with `curl https://<api address>/readyz`, which answers `{"status":"ready"}`. Then open the screen's address, create an account and run an analysis with the fictional samples in `samples/`.

## 6. Turn on Claude (optional)

Without a key the app uses its rule-based job-description parser, and rewrite suggestions are off. To turn Claude on, store the key as a secret of the API app and point an environment variable at it:

```bash
read -rs -p "Anthropic API key: " ANTHROPIC_API_KEY; echo
az containerapp secret set --name "$PREFIX-api" --resource-group "$RG" \
  --secrets anthropic-api-key="$ANTHROPIC_API_KEY"
az containerapp update --name "$PREFIX-api" --resource-group "$RG" \
  --container-name api --set-env-vars ANTHROPIC_API_KEY=secretref:anthropic-api-key
```

The update starts a new revision of the API with the key. A later run of the template replaces the app's secrets and settings with the template's, which removes the key again. Either repeat these two commands after it, or pass the key to the template with `anthropicApiKey="$ANTHROPIC_API_KEY"` on the `--parameters` line.

## 7. Read the logs

```bash
# The API's JSON logs, as they arrive:
az containerapp logs show --name "$PREFIX-api" --resource-group "$RG" --container api --follow

# ClamAV, the screen, and the platform's own messages (failed starts, probes):
az containerapp logs show --name "$PREFIX-api" --resource-group "$RG" --container clamav --tail 50
az containerapp logs show --name "$PREFIX-ui" --resource-group "$RG" --container ui --tail 50
az containerapp logs show --name "$PREFIX-api" --resource-group "$RG" --type system
```

The logs carry request ids, user ids, route templates, status codes and timings. They never hold emails, passwords, tokens, resume text or job-description text. Older logs are in the Log Analytics workspace (`<prefix>-logs`) for 30 days; in the Azure portal, open it and choose Logs.

## 8. Account administration

There is no email in 1.0, so there is no "forgot my password" link. To set a new password for someone, or to delete an account by email, open a shell in the API container and use the admin command:

```bash
az containerapp exec --name "$PREFIX-api" --resource-group "$RG" --container api --command /bin/sh
# inside the container:
python -m app.admin reset-password person@example.com
python -m app.admin delete-user person@example.com
```

Resetting a password ends every session of that account. Tell the person their new password over a channel you both trust.

## 9. Deploy a new version

Push the new tag and wait for the release workflow. Then either run the "Deploy to Azure" workflow (below), or by hand:

```bash
TAG=v1.0.1
az containerapp job update --name "$PREFIX-migrate" --resource-group "$RG" \
  --container-name migrate --image "ghcr.io/$OWNER/resume-evidence-matcher-api:$TAG"
az containerapp job start --name "$PREFIX-migrate" --resource-group "$RG"
# wait for Succeeded as in step 4, then:
az containerapp update --name "$PREFIX-api" --resource-group "$RG" \
  --container-name api --image "ghcr.io/$OWNER/resume-evidence-matcher-api:$TAG"
az containerapp update --name "$PREFIX-ui" --resource-group "$RG" \
  --container-name ui --image "ghcr.io/$OWNER/resume-evidence-matcher-ui:$TAG"
```

Migrations always run before the API moves to the new image, so the new API never starts on an old schema.

### The "Deploy to Azure" workflow

`.github/workflows/deploy-azure.yml` runs those steps from GitHub Actions when you start it by hand (Actions, Deploy to Azure, Run workflow, with the tag). It signs in with OpenID Connect, so no Azure password or key is stored in GitHub. Set it up once. The commands below use the GitHub CLI (`gh`) for the secrets and variables; you can also add them under the repository's Settings, Secrets and variables, Actions.

```bash
REPO=your-github-user/resume-evidence-matcher   # owner/name of your GitHub repository

APP_ID=$(az ad app create --display-name resume-matcher-deploy --query appId --output tsv)
az ad sp create --id "$APP_ID"
SUBSCRIPTION_ID=$(az account show --query id --output tsv)
TENANT_ID=$(az account show --query tenantId --output tsv)

# Allowed to change resources in this resource group only.
az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG"

# Trust tokens from this repository's "production" environment, which the workflow uses.
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-production\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:$REPO:environment:production\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"

gh secret set AZURE_CLIENT_ID --repo "$REPO" --body "$APP_ID"
gh secret set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT_ID"
gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUBSCRIPTION_ID"
gh variable set AZURE_RESOURCE_GROUP --repo "$REPO" --body "$RG"
gh variable set AZURE_NAME_PREFIX --repo "$REPO" --body "$PREFIX"
```

The workflow creates the `production` environment on its first run if it doesn't exist. To make every deploy wait for your approval, add yourself as a required reviewer of that environment in the repository settings.

## 10. Count each visitor for rate limits (optional)

The API limits logins, analyses, suggestions and exports per account and per client address. It reads the client address from `X-Forwarded-For` only when the request comes through an address in `TRUSTED_PROXIES`. The template trusts the private address ranges, which covers the Container Apps ingress in front of the API. Requests from the screen reach the API from the screen's outbound address, so by default every visitor of the screen counts as one address there (the per-account limits still apply to each person). The screen passes on the visitor's address, and the API uses it once the screen's outbound addresses are trusted too:

```bash
UI_ADDRESSES=$(az containerapp show --name "$PREFIX-ui" --resource-group "$RG" \
  --query "join(',', properties.outboundIpAddresses)" --output tsv)
```

Then run the step 5 command again with `trustedProxies="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,$UI_ADDRESSES"` added. Only add addresses you control: any request from a trusted address can name its own client address.

## 11. Tear it all down

```bash
az group delete --name "$RG" --yes --no-wait
az ad app delete --id "$APP_ID"   # only if you set up the deploy workflow
```

Deleting the resource group deletes every resource in it, the database and its backups included, and stops all charges for them. A deleted Log Analytics workspace stays recoverable for 14 days, so a new workspace with the same name in that time may need another prefix.

## What it costs

Azure bills each part separately, and prices depend on the region. Use the Azure pricing calculator (https://azure.microsoft.com/pricing/calculator/) with the sizes below for a current figure. This guide doesn't quote prices because they change.

| Part | How Azure bills it | What this setup uses |
| --- | --- | --- |
| Container Apps (Consumption) | Per vCPU-second and GiB-second while replicas run, plus requests, after a monthly free grant. A replica with no traffic is billed at a lower idle rate. | The API app (0.5 vCPU and 1 GiB) with its ClamAV container (1.5 vCPU and 3 GiB), and the screen (0.5 vCPU and 1 GiB), all running all the time because each keeps one replica. The migration job only while it runs. |
| Postgres Flexible Server | Compute per hour for the chosen size, storage per GiB-month, and backup storage beyond the amount included with the server. | Burstable Standard_B1ms, 32 GiB of storage, 7 days of backups. |
| Log Analytics | Per GB of logs ingested, after a free daily amount, and retention beyond the included period. | The containers' logs, kept 30 days. |
| Bandwidth | Data leaving Azure, after a free monthly amount. | Pages, reports and Word files sent to visitors. |
| GitHub Container Registry | Billed by GitHub, not Azure. Public packages are free. | The two images. |
| Anthropic API | Billed by Anthropic per token, only with a key set. | Job-description parsing per analysis, and rewrites when asked for. `LLM_MAX_SUGGESTIONS` caps rewrites per analysis. |

The ClamAV container is the largest steady cost, followed by the database. `az postgres flexible-server stop --resource-group "$RG" --name <server name>` stops the database's compute charges while you aren't using it (Azure starts it again after 7 days), and the API isn't ready while it is stopped. Step 11 stops everything.

## Security notes and known gaps

- Traffic from browsers is encrypted by the Container Apps ingress (TLS 1.2 or 1.3, with certificates Azure manages). The API sends `Strict-Transport-Security` in production.
- The database connection is encrypted on both ends: the server requires TLS (`require_secure_transport`) and the app refuses to start in production without `sslmode=require`. `sslmode=require` doesn't verify the server's certificate; `verify-full` would also need the certificate authority's root certificate in the image, which 1.0 doesn't include.
- The database firewall rule allows connections from Azure services, which includes other customers' services as well as yours. A connection still needs the password. A private network (VNet integration and private access for Postgres) closes that, and isn't in this template yet.
- ClamAV runs next to the API, so uploads never leave the app to be scanned. Its signatures come with the image and freshclam updates them while it runs. Without a volume for them, each new revision starts from the signatures in the image.
- The rate limits are in the API's memory. Running more than one replica would multiply them, which is why the template fixes the count at one.
