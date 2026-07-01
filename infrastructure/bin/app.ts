#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { DslApiStack } from '../lib/dsl-api-stack';

const app = new cdk.App();

new DslApiStack(app, 'DslReferenceStack', {
  description: 'DSL Reference Implementation - Control Plane',
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});
