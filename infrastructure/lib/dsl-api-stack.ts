import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigatewayv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import * as path from 'path';
import * as fs from 'fs';

export class DslApiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ─── KMS Asymmetric Signing Key ──────────────────────────────────────
    const signingKey = new kms.Key(this, 'DslSigningKey', {
      keySpec: kms.KeySpec.RSA_2048,
      keyUsage: kms.KeyUsage.SIGN_VERIFY,
      alias: 'dsl-lease-signing',
      description: 'RSA-2048 key for signing DSL lease JWT tokens',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ─── DynamoDB Tables ─────────────────────────────────────────────────

    const entitlementsTable = new dynamodb.Table(this, 'EntitlementsTable', {
      tableName: 'DslEntitlements',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const leasesTable = new dynamodb.Table(this, 'LeasesTable', {
      tableName: 'DslLeases',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    leasesTable.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
    });

    const usageTable = new dynamodb.Table(this, 'UsageRecordsTable', {
      tableName: 'DslUsageRecords',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const connectionsTable = new dynamodb.Table(this, 'WsConnectionsTable', {
      tableName: 'DslWsConnections',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    connectionsTable.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
    });

    // ─── Lambda Functions ────────────────────────────────────────────────

    const lambdaEnvironment = {
      ENTITLEMENTS_TABLE: entitlementsTable.tableName,
      LEASES_TABLE: leasesTable.tableName,
      USAGE_TABLE: usageTable.tableName,
      CONNECTIONS_TABLE: connectionsTable.tableName,
      KMS_KEY_ID: signingKey.keyId,
      KMS_KEY_ARN: signingKey.keyArn,
    };

    const leaseHandler = new lambda.Function(this, 'LeaseHandler', {
      functionName: 'dsl-lease-handler',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../control-plane/lambdas/lease_handler')),
      timeout: cdk.Duration.seconds(30),
      environment: lambdaEnvironment,
    });

    const usageHandler = new lambda.Function(this, 'UsageHandler', {
      functionName: 'dsl-usage-handler',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../control-plane/lambdas/usage_handler')),
      timeout: cdk.Duration.seconds(10),
      environment: lambdaEnvironment,
    });

    const jwksHandler = new lambda.Function(this, 'JwksHandler', {
      functionName: 'dsl-jwks-handler',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../control-plane/lambdas/jwks_handler')),
      timeout: cdk.Duration.seconds(10),
      environment: {
        KMS_KEY_ID: signingKey.keyId,
        KMS_KEY_ARN: signingKey.keyArn,
      },
    });

    const wsHandler = new lambda.Function(this, 'WsHandler', {
      functionName: 'dsl-ws-handler',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../control-plane/lambdas/ws_handler')),
      timeout: cdk.Duration.seconds(10),
      environment: lambdaEnvironment,
    });

    // ─── IAM Permissions (Least Privilege) ───────────────────────────────

    entitlementsTable.grantReadWriteData(leaseHandler);
    leasesTable.grantReadWriteData(leaseHandler);
    connectionsTable.grantReadData(leaseHandler);
    signingKey.grant(leaseHandler, 'kms:Sign', 'kms:GetPublicKey');

    usageTable.grantReadWriteData(usageHandler);

    signingKey.grant(jwksHandler, 'kms:GetPublicKey');

    connectionsTable.grantReadWriteData(wsHandler);

    // ─── HTTP API (REST) ─────────────────────────────────────────────────

    const httpApi = new apigatewayv2.HttpApi(this, 'DslHttpApi', {
      apiName: 'dsl-reference-api',
      description: 'DSL Reference Implementation REST API',
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [apigatewayv2.CorsHttpMethod.ANY],
        allowHeaders: ['*'],
      },
    });

    const leaseIntegration = new integrations.HttpLambdaIntegration('LeaseIntegration', leaseHandler);
    const usageIntegration = new integrations.HttpLambdaIntegration('UsageIntegration', usageHandler);
    const jwksIntegration = new integrations.HttpLambdaIntegration('JwksIntegration', jwksHandler);

    // Lease routes
    httpApi.addRoutes({ path: '/v1/leases', methods: [apigatewayv2.HttpMethod.POST], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/leases/{leaseId}/renew', methods: [apigatewayv2.HttpMethod.POST], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/leases/{leaseId}/reissue', methods: [apigatewayv2.HttpMethod.POST], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/leases/{leaseId}/finalizeReissue', methods: [apigatewayv2.HttpMethod.POST], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/leases/{leaseId}', methods: [apigatewayv2.HttpMethod.DELETE], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/admin/reset', methods: [apigatewayv2.HttpMethod.POST], integration: leaseIntegration });
    httpApi.addRoutes({ path: '/v1/admin/observability', methods: [apigatewayv2.HttpMethod.GET], integration: leaseIntegration });

    // Usage route
    httpApi.addRoutes({ path: '/v1/usage-records', methods: [apigatewayv2.HttpMethod.POST], integration: usageIntegration });

    // JWKS route
    httpApi.addRoutes({ path: '/.well-known/jwks.json', methods: [apigatewayv2.HttpMethod.GET], integration: jwksIntegration });

    // ─── WebSocket API ───────────────────────────────────────────────────

    const wsApi = new apigatewayv2.WebSocketApi(this, 'DslWsApi', {
      apiName: 'dsl-reference-ws',
      connectRouteOptions: {
        integration: new integrations.WebSocketLambdaIntegration('WsConnectIntegration', wsHandler),
      },
      disconnectRouteOptions: {
        integration: new integrations.WebSocketLambdaIntegration('WsDisconnectIntegration', wsHandler),
      },
      defaultRouteOptions: {
        integration: new integrations.WebSocketLambdaIntegration('WsDefaultIntegration', wsHandler),
      },
    });

    const wsStage = new apigatewayv2.WebSocketStage(this, 'DslWsStage', {
      webSocketApi: wsApi,
      stageName: 'prod',
      autoDeploy: true,
    });

    // Grant lease handler permission to push messages via WebSocket Management API
    leaseHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: ['execute-api:ManageConnections'],
      resources: [
        `arn:aws:execute-api:${this.region}:${this.account}:${wsApi.apiId}/prod/POST/@connections/*`,
      ],
    }));

    // Pass WebSocket endpoint to lease handler for push operations
    leaseHandler.addEnvironment('WS_API_ENDPOINT', wsStage.callbackUrl);

    // ─── Stack Outputs ───────────────────────────────────────────────────

    new cdk.CfnOutput(this, 'RestApiUrl', {
      value: httpApi.apiEndpoint,
      description: 'REST API endpoint URL',
    });

    new cdk.CfnOutput(this, 'WsApiUrl', {
      value: wsStage.url,
      description: 'WebSocket API endpoint URL',
    });

    new cdk.CfnOutput(this, 'JwksUrl', {
      value: `${httpApi.apiEndpoint}/.well-known/jwks.json`,
      description: 'JWKS endpoint URL',
    });

    new cdk.CfnOutput(this, 'KmsKeyId', {
      value: signingKey.keyId,
      description: 'KMS signing key ID',
    });

    // ─── Seed Data (auto-loaded on deploy) ───────────────────────────────

    const seedData = JSON.parse(fs.readFileSync(path.join(__dirname, '../seed/seed-data.json'), 'utf8'));

    for (let i = 0; i < seedData.entitlements.length; i++) {
      const item = seedData.entitlements[i];
      new cr.AwsCustomResource(this, `SeedEntitlement${i}`, {
        onCreate: {
          service: 'DynamoDB',
          action: 'putItem',
          parameters: {
            TableName: entitlementsTable.tableName,
            Item: this.toDynamoDbItem(item),
          },
          physicalResourceId: cr.PhysicalResourceId.of(`seed-${item.PK}-${item.SK}`),
        },
        onUpdate: {
          service: 'DynamoDB',
          action: 'putItem',
          parameters: {
            TableName: entitlementsTable.tableName,
            Item: this.toDynamoDbItem(item),
          },
          physicalResourceId: cr.PhysicalResourceId.of(`seed-${item.PK}-${item.SK}`),
        },
        policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
          resources: [entitlementsTable.tableArn],
        }),
      });
    }
  }

  /**
   * Convert a plain JS object to DynamoDB item format.
   */
  private toDynamoDbItem(obj: Record<string, any>): Record<string, any> {
    const item: Record<string, any> = {};
    for (const [key, value] of Object.entries(obj)) {
      item[key] = this.toDynamoDbValue(value);
    }
    return item;
  }

  private toDynamoDbValue(value: any): any {
    if (typeof value === 'string') return { S: value };
    if (typeof value === 'number') return { N: String(value) };
    if (typeof value === 'boolean') return { BOOL: value };
    if (Array.isArray(value)) return { L: value.map(v => this.toDynamoDbValue(v)) };
    if (typeof value === 'object' && value !== null) return { M: this.toDynamoDbItem(value) };
    return { NULL: true };
  }
}
