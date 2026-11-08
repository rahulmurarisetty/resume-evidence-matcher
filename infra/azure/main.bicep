// Resume evidence matcher on Azure Container Apps.
//
// Creates, in the resource group it is deployed to:
//   - a Log Analytics workspace for the container logs
//   - a Container Apps environment (Consumption workload profile)
//   - a Postgres Flexible Server that only accepts TLS connections, with one database
//   - the API container app, with ClamAV running next to it as a sidecar container
//   - the Streamlit screen as a second container app
//   - a manual Container Apps job that runs the database migrations once
//
// A first deploy runs in two steps (deployApps=false, the migration job, then the
// default deployApps=true), so the API never starts on an empty database.
//
// Both apps get HTTPS-only external ingress. Each runs exactly one replica: the
// rate limits are kept in the API's memory, and the screen keeps each visitor's
// session in its own memory, so neither may be scaled out as it is.
//
// Secrets (the database URL with its password, the optional Anthropic key and the
// optional registry password) are stored as Container App secrets and reach the
// containers only as environment variables that reference them.
//
// See docs/deploy-azure.md for the commands.

targetScope = 'resourceGroup'

@description('Azure region for every resource. Defaults to the resource group\'s region.')
param location string = resourceGroup().location

@description('Short lowercase prefix for resource names, such as "rem". Letters and digits only.')
@minLength(2)
@maxLength(12)
param namePrefix string = 'rem'

@description('API image, such as ghcr.io/<owner>/resume-evidence-matcher-api:v1.0.0 (or the -ml tag).')
param apiImage string

@description('Screen image, such as ghcr.io/<owner>/resume-evidence-matcher-ui:v1.0.0.')
param uiImage string

@description('ClamAV image. A feature-release tag, as ClamAV recommends.')
param clamavImage string = 'docker.io/clamav/clamav:1.4'

@description('Postgres administrator login. Postgres reserves some names, such as "postgres" and "azure_superuser".')
param postgresAdminLogin string = 'matcher'

@secure()
@minLength(12)
@description('Postgres administrator password. Pass it at deploy time; never write it in a file.')
param postgresAdminPassword string

@description('Name of the application database.')
param postgresDatabaseName string = 'matcher'

@description('Postgres compute size. Standard_B1ms is the smallest Burstable size.')
param postgresSkuName string = 'Standard_B1ms'

@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param postgresTier string = 'Burstable'

@allowed(['14', '15', '16'])
param postgresVersion string = '16'

@minValue(32)
param postgresStorageGb int = 32

@secure()
@description('Optional Anthropic API key. Empty leaves Claude off. It can also be set later with az containerapp secret set (see docs/deploy-azure.md).')
param anthropicApiKey string = ''

@description('Registry login server for the images.')
param registryServer string = 'ghcr.io'

@description('Registry user name. Leave empty when the images are public.')
param registryUsername string = ''

@secure()
@description('Registry password or token (for ghcr.io, a token with read:packages). Leave empty when the images are public.')
param registryPassword string = ''

@description('vCPUs for the API container. With the ClamAV sidecar, the app total must be a valid Consumption size (0.25 vCPU steps, 2 GiB per vCPU).')
param apiCpu string = '0.5'

@description('Memory for the API container. Use 2Gi or more with the -ml image.')
param apiMemory string = '1Gi'

@description('vCPUs for the ClamAV sidecar.')
param clamavCpu string = '1.5'

@description('Memory for the ClamAV sidecar. ClamAV needs about 3 GiB, and briefly more while it reloads its signatures.')
param clamavMemory string = '3Gi'

@description('Addresses whose X-Forwarded-For the API trusts. The private and shared ranges cover the Container Apps ingress. Add the screen\'s outbound addresses to count each visitor separately (see docs/deploy-azure.md).')
param trustedProxies string = '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10'

@description('false creates everything except the two apps, so the migration job can run before the API first starts (production refuses to start while migrations are pending). See docs/deploy-azure.md.')
param deployApps bool = true

@description('Days Log Analytics keeps the logs.')
@minValue(30)
param logRetentionDays int = 30

var apiName = '${namePrefix}-api'
var uiName = '${namePrefix}-ui'
var jobName = '${namePrefix}-migrate'
var postgresName = '${namePrefix}-pg-${uniqueString(resourceGroup().id)}'
var useRegistry = !empty(registryUsername)
var useClaude = !empty(anthropicApiKey)

var registrySecrets = useRegistry ? [{ name: 'registry-password', value: registryPassword }] : []
var registries = useRegistry
  ? [{ server: registryServer, username: registryUsername, passwordSecretRef: 'registry-password' }]
  : []
// psycopg 3, and TLS required on the client side too. The app refuses to start in
// production without sslmode=require.
var databaseUrl = 'postgresql+psycopg://${postgresAdminLogin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/${postgresDatabaseName}?sslmode=require'
var databaseSecrets = [{ name: 'database-url', value: databaseUrl }]
var claudeSecrets = useClaude ? [{ name: 'anthropic-api-key', value: anthropicApiKey }] : []
var claudeEnv = useClaude ? [{ name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }] : []

var uiUrl = 'https://${uiName}.${environment.properties.defaultDomain}'
var apiUrl = 'https://${apiName}.${environment.properties.defaultDomain}'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: logRetentionDays
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  sku: {
    name: postgresSkuName
    tier: postgresTier
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    storage: {
      storageSizeGB: postgresStorageGb
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

// Connections from Azure services only (the 0.0.0.0 rule), so the container apps can
// reach the server. Anyone connecting still needs the password, over TLS.
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// On by default; set here so the template states it. Changes to one server run one
// at a time, hence the dependsOn chain.
resource requireTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'require_secure_transport'
  properties: {
    value: 'on'
    source: 'user-override'
  }
  dependsOn: [allowAzure]
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [requireTls]
}

resource api 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: apiName
  location: location
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: concat(databaseSecrets, claudeSecrets, registrySecrets)
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json(apiCpu)
            memory: apiMemory
          }
          env: concat(
            [
              { name: 'APP_ENV', value: 'production' }
              { name: 'DATABASE_URL', secretRef: 'database-url' }
              { name: 'AUTH_MODE', value: 'required' }
              // The sidecar shares the app's network, so clamd is on localhost.
              { name: 'SCANNER', value: 'clamav' }
              { name: 'CLAMAV_HOST', value: 'localhost' }
              { name: 'CLAMAV_PORT', value: '3310' }
              { name: 'CORS_ORIGINS', value: uiUrl }
              { name: 'TRUSTED_PROXIES', value: trustedProxies }
              { name: 'LOG_LEVEL', value: 'INFO' }
              { name: 'LLM_ENABLED', value: 'auto' }
              { name: 'SEMANTIC_MATCHING', value: 'auto' }
            ],
            claudeEnv
          )
          probes: [
            {
              // Up to 10 minutes for the first start of the -ml image (model download).
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 10
              failureThreshold: 60
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 30
            }
            {
              // Ready only when Postgres and ClamAV both answer.
              type: 'Readiness'
              httpGet: { path: '/readyz', port: 8000 }
              periodSeconds: 15
              failureThreshold: 3
            }
          ]
        }
        {
          name: 'clamav'
          image: clamavImage
          resources: {
            cpu: json(clamavCpu)
            memory: clamavMemory
          }
          probes: [
            {
              // Loading the signatures takes a minute or two.
              type: 'Startup'
              tcpSocket: { port: 3310 }
              periodSeconds: 10
              failureThreshold: 60
            }
            {
              type: 'Liveness'
              tcpSocket: { port: 3310 }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [database]
}

resource ui 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: uiName
  location: location
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8501
        transport: 'auto'
        allowInsecure: false
      }
      secrets: registrySecrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: uiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [{ name: 'API_URL', value: apiUrl }]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/_stcore/health', port: 8501 }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// Run once after the first deploy and after each upgrade, before the API starts on
// the new version: az containerapp job start (see docs/deploy-azure.md). The image's
// entrypoint runs `alembic upgrade head` (RUN_MIGRATIONS=true), then the command
// prints the revision and fails if any migration is still pending.
resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: concat(databaseSecrets, registrySecrets)
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: apiImage
          args: ['python', '-m', 'app.storage.migrations']
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
            { name: 'RUN_MIGRATIONS', value: 'true' }
          ]
        }
      ]
    }
  }
  dependsOn: [database]
}

// The apps' addresses are known before they exist: <app name>.<environment domain>.
output apiUrl string = apiUrl
output uiUrl string = uiUrl
output migrateJobName string = migrate.name
output postgresServerName string = postgres.name
output postgresHost string = postgres.properties.fullyQualifiedDomainName
