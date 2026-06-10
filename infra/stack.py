import aws_cdk as cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

REPO_ROOT = ".."
LAMBDA_RUNTIME = _lambda.Runtime.PYTHON_3_12

_ASSET_EXCLUDE = [
    "cdk.out", ".venv", "frontend", "infra", ".git", ".github",
    "node_modules", "**/__pycache__", "**/*.pyc", "**/*.pyo", "tests",
    "TODO.md", "CLAUDE.md", "fetcher-spikes", "docs",
]


class NrlPredictorV2Stack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Secrets (shared with v1) ─────────────────────────────────────────
        anthropic_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "AnthropicSecret", "nrl-predictor/anthropic-api-key"
        )
        tavily_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "TavilySecret", "nrl-predictor/tavily-api-key"
        )

        # ── Existing shared tables (imported by name, not created) ───────────
        # The v2 stack reads from the same v1 data tables.
        predictions_table = dynamodb.Table.from_table_name(self, "Predictions", "predictions")
        teams_table = dynamodb.Table.from_table_name(self, "Teams", "teams")
        results_table = dynamodb.Table.from_table_name(self, "Results", "results")
        injuries_table = dynamodb.Table.from_table_name(self, "Injuries", "injuries")
        weather_table = dynamodb.Table.from_table_name(self, "Weather", "weather")
        claude_usage_table = dynamodb.Table.from_table_name(self, "ClaudeUsage", "claude_usage")
        retrospectives_table = dynamodb.Table.from_table_name(self, "Retrospectives", "retrospectives")
        raw_bucket = s3.Bucket.from_bucket_name(self, "RawScrapes", "nrl-predictor-raw-scrapes")

        # ── New table: agent_traces ──────────────────────────────────────────
        agent_traces_table = dynamodb.Table(
            self, "AgentTraces",
            table_name="agent_traces",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="generatedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ── Lambda layer for Python dependencies ─────────────────────────────
        deps_layer = _lambda.LayerVersion(
            self, "DepsLayer",
            layer_version_name="nrl-predictor-v2-deps",
            compatible_runtimes=[LAMBDA_RUNTIME],
            description="nrl-predictor-v2 Python dependencies",
            code=_lambda.Code.from_asset(
                REPO_ROOT,
                exclude=_ASSET_EXCLUDE,
                bundling=cdk.BundlingOptions(
                    image=LAMBDA_RUNTIME.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install"
                        " requests beautifulsoup4 lxml boto3 tavily-python"
                        " langchain-anthropic langchain-core langgraph"
                        " --target /asset-output/python --no-cache-dir --quiet",
                    ],
                ),
            ),
        )

        # Common Lambda settings
        common_env = {
            "TEAMS_TABLE": "teams",
            "RESULTS_TABLE": "results",
            "INJURIES_TABLE": "injuries",
            "WEATHER_TABLE": "weather",
            "CLAUDE_USAGE_TABLE": "claude_usage",
            "RETROSPECTIVES_TABLE": "retrospectives",
            "PREDICTIONS_TABLE": "predictions",
            "AGENT_TRACES_TABLE": "agent_traces",
            "RAW_BUCKET": raw_bucket.bucket_name,
            "BUDGET_THRESHOLD_USD": "50.0",
        }

        code = _lambda.Code.from_asset(
            REPO_ROOT,
            exclude=_ASSET_EXCLUDE,
        )

        # ── Agent Lambda ─────────────────────────────────────────────────────
        agent_fn = _lambda.Function(
            self, "AgentFn",
            function_name="nrl-predictor-v2-agent",
            runtime=LAMBDA_RUNTIME,
            handler="agent.lambda_handler.lambda_handler",
            code=code,
            timeout=cdk.Duration.minutes(8),
            memory_size=512,
            environment=common_env,
            layers=[deps_layer],
        )

        # ── Orchestrator Lambda ──────────────────────────────────────────────
        orchestrator_fn = _lambda.Function(
            self, "OrchestratorFn",
            function_name="nrl-predictor-v2-orchestrator",
            runtime=LAMBDA_RUNTIME,
            handler="orchestrator.lambda_handler.lambda_handler",
            code=code,
            timeout=cdk.Duration.minutes(5),
            memory_size=256,
            environment={
                **common_env,
                "AGENT_FUNCTION_NAME": "nrl-predictor-v2-agent",
                "AGENT_INVOKE_STAGGER_SECONDS": "8",
            },
            layers=[deps_layer],
        )

        # ── API Lambda ───────────────────────────────────────────────────────
        # Share the v1 API: it joins predictions by matchId and round.
        # The v2 predictions land in the same table with new fields.
        # A dedicated v2 API endpoint lets the frontend query v2 predictions
        # separately during the shadow-mode period.
        rate_limits_table = dynamodb.Table.from_table_name(self, "RateLimits", "nrl-rate-limits")
        metrics_table = dynamodb.Table.from_table_name(self, "Metrics", "metrics")
        odds_table_name = "odds"

        api_fn = _lambda.Function(
            self, "ApiFn",
            function_name="nrl-predictor-v2-api",
            runtime=LAMBDA_RUNTIME,
            handler="api.router.lambda_handler",
            code=code,
            timeout=cdk.Duration.seconds(15),
            memory_size=256,
            environment={
                **common_env,
                "RATE_LIMITS_TABLE": "nrl-rate-limits",
                "ODDS_TABLE": odds_table_name,
            },
            layers=[deps_layer],
        )

        # ── IAM grants ───────────────────────────────────────────────────────
        for tbl in (teams_table, results_table, claude_usage_table, injuries_table, weather_table, retrospectives_table):
            tbl.grant_read_data(agent_fn)
        predictions_table.grant_read_write_data(agent_fn)
        agent_traces_table.grant_read_write_data(agent_fn)
        raw_bucket.grant_read(agent_fn)
        anthropic_secret.grant_read(agent_fn)
        tavily_secret.grant_read(agent_fn)

        teams_table.grant_read_data(orchestrator_fn)
        raw_bucket.grant_read_write(orchestrator_fn)
        agent_fn.grant_invoke(orchestrator_fn)
        # Orchestrator also needs to write team sheets inline
        teams_table.grant_read_write_data(orchestrator_fn)

        for tbl in (predictions_table, metrics_table, rate_limits_table, retrospectives_table):
            tbl.grant_read_write_data(api_fn)
        results_table.grant_read_data(api_fn)

        # ── API Gateway ───────────────────────────────────────────────────────
        api = apigwv2.HttpApi(
            self, "HttpApi",
            api_name="nrl-predictor-v2-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_methods=[apigwv2.CorsHttpMethod.GET],
                allow_origins=["*"],
            ),
        )
        api_integration = integrations.HttpLambdaIntegration("ApiIntegration", api_fn)
        api.add_routes(path="/predictions/{round}", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/health", methods=[apigwv2.HttpMethod.GET], integration=api_integration)

        # ── EventBridge (shadow mode — same schedule as v1 but staggered +4s) ─
        # Tuesday 06:30 UTC
        tue_rule = events.Rule(
            self, "TueRule",
            rule_name="nrl-v2-tuesday",
            schedule=events.Schedule.cron(minute="34", hour="6", week_day="TUE"),
        )
        tue_rule.add_target(targets.LambdaFunction(
            orchestrator_fn,
            event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
        ))

        # Thursday 07:00 UTC
        events.Rule(
            self, "ThuRule",
            rule_name="nrl-v2-thursday",
            schedule=events.Schedule.cron(minute="4", hour="7", week_day="THU"),
            targets=[targets.LambdaFunction(
                orchestrator_fn,
                event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
            )],
        )

        # Friday 07:04 UTC
        events.Rule(
            self, "FriRule",
            rule_name="nrl-v2-friday",
            schedule=events.Schedule.cron(minute="4", hour="7", week_day="FRI"),
            targets=[targets.LambdaFunction(
                orchestrator_fn,
                event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
            )],
        )

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "V2ApiEndpoint", value=api.api_endpoint)
        cdk.CfnOutput(self, "V2AgentFunctionArn", value=agent_fn.function_arn)
        cdk.CfnOutput(self, "AgentTracesTableName", value=agent_traces_table.table_name)
