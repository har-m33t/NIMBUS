/**
 * Cognito configuration.
 *
 * These values come from the CloudFormation stack outputs after deploying
 * template.yaml. During development, set them in a `.env` file:
 *
 *   VITE_COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx
 *   VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
 *   VITE_COGNITO_REGION=us-east-1
 */
export const COGNITO_CONFIG = {
  userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || "",
  clientId: import.meta.env.VITE_COGNITO_CLIENT_ID || "",
  region: import.meta.env.VITE_COGNITO_REGION || "us-east-1",
} as const;
