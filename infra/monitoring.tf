# One CloudWatch dashboard for the whole project, plus 2 log metric filters.
# Free: always-free tier covers 3 dashboards (50 metrics each) and 10 custom
# metrics; this uses 1 dashboard, ~28 metrics and 2 custom metrics.
# No Logs Insights widgets (those bill per GB scanned).

resource "aws_cloudwatch_log_metric_filter" "blocked" {
  name           = "${var.prefix}-blocked-by-rule"
  log_group_name = aws_cloudwatch_log_group.gateway.name
  pattern        = "BLOCKED"
  metric_transformation {
    name      = "BlockedByRule"
    namespace = "llm-gateway"
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "state_changes" {
  name           = "${var.prefix}-state-changes"
  log_group_name = aws_cloudwatch_log_group.gateway.name
  pattern        = "\"STATE_CHANGE\""
  metric_transformation {
    name      = "StateChanges"
    namespace = "llm-gateway"
    value     = "1"
  }
}

locals {
  fns     = ["gateway", "demo", "bot"]
  tables  = [aws_dynamodb_table.agents.name, aws_dynamodb_table.counters.name, aws_dynamodb_table.usage.name, aws_dynamodb_table.incidents.name]
  console = "https://${var.region}.console.aws.amazon.com"

  # r1..r4 / w1..w4 = one hidden metric per table; rt / wt = total per second
  ddb_kind = { ConsumedReadCapacityUnits = "r", ConsumedWriteCapacityUnits = "w" }
  ddb_total = { for m, k in local.ddb_kind : m => concat(
    [[{ expression = "(FILL(${k}1,0)+FILL(${k}2,0)+FILL(${k}3,0)+FILL(${k}4,0))/60", label = k == "r" ? "read units/s" : "write units/s", id = "${k}t" }]],
    [for i, t in local.tables : ["AWS/DynamoDB", m, "TableName", t, { id = "${k}${i + 1}", visible = false }]]
  ) }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.prefix
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 3
        properties = {
          markdown = join("", [
            "## llm-gateway: serverless LLM gateway with runaway-agent protection\n",
            "[Live dashboard](https://dheepakkaran.github.io/llm-gateway/) · ",
            "[Resource group](${local.console}/resource-groups/group/llm-gateway?region=${var.region}) · ",
            "[Free Tier usage](https://${var.region}.console.aws.amazon.com/costmanagement/home#/free-tier) · ",
            "[Bills](https://${var.region}.console.aws.amazon.com/costmanagement/home#/bills) · ",
            "[Gateway logs](${local.console}/cloudwatch/home?region=${var.region}#logsV2:log-groups/log-group/$252Faws$252Flambda$252F${var.prefix}-gateway)\n\n",
            "Free-tier limits: Lambda 1M requests/month · DynamoDB 24 of 25 RCU/WCU provisioned (throttles should stay at 0)."
          ])
        }
      },
      {
        type = "metric", x = 0, y = 3, width = 8, height = 6
        properties = {
          title   = "Lambda invocations (per 5 min)", region = var.region, view = "timeSeries", stat = "Sum", period = 300
          metrics = [for f in local.fns : ["AWS/Lambda", "Invocations", "FunctionName", "${var.prefix}-${f}", { label = f }]]
        }
      },
      {
        type = "metric", x = 8, y = 3, width = 8, height = 6
        properties = {
          title = "Lambda errors and throttles", region = var.region, view = "timeSeries", stat = "Sum", period = 300
          metrics = concat(
            [for f in local.fns : ["AWS/Lambda", "Errors", "FunctionName", "${var.prefix}-${f}", { label = "${f} errors" }]],
            [["AWS/Lambda", "Throttles", "FunctionName", "${var.prefix}-gateway", { label = "gateway throttles" }]]
          )
        }
      },
      {
        type = "metric", x = 16, y = 3, width = 8, height = 6
        properties = {
          title = "Gateway latency (ms)", region = var.region, view = "timeSeries", period = 300
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", "${var.prefix}-gateway", { stat = "p50", label = "p50" }],
            ["AWS/Lambda", "Duration", "FunctionName", "${var.prefix}-gateway", { stat = "p95", label = "p95" }]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 9, width = 8, height = 6
        properties = {
          title = "Guard: blocked by rules and state changes (per 5 min)", region = var.region, view = "timeSeries", stat = "Sum", period = 300
          metrics = [
            ["llm-gateway", "BlockedByRule", { label = "blocked by a rule" }],
            ["llm-gateway", "StateChanges", { label = "suspend / kill / resume" }]
          ]
        }
      },
      {
        type = "metric", x = 8, y = 9, width = 8, height = 6
        properties = {
          title       = "DynamoDB capacity used (units/s, free limit 24)", region = var.region, view = "timeSeries", stat = "Sum", period = 60
          metrics     = concat(local.ddb_total["ConsumedReadCapacityUnits"], local.ddb_total["ConsumedWriteCapacityUnits"])
          annotations = { horizontal = [{ label = "provisioned (24)", value = 24 }] }
          yAxis       = { left = { min = 0 } }
        }
      },
      {
        type = "metric", x = 16, y = 9, width = 8, height = 6
        properties = {
          title = "DynamoDB throttled requests (should be 0)", region = var.region, view = "timeSeries", stat = "Sum", period = 300
          metrics = concat(
            [for t in local.tables : ["AWS/DynamoDB", "ReadThrottleEvents", "TableName", t, { label = "${t} reads" }]],
            [for t in local.tables : ["AWS/DynamoDB", "WriteThrottleEvents", "TableName", t, { label = "${t} writes" }]]
          )
        }
      },
      {
        type = "metric", x = 0, y = 15, width = 8, height = 6
        properties = {
          title   = "Estimated AWS charges (USD)", region = "us-east-1", view = "singleValue", stat = "Maximum", period = 21600
          metrics = [["AWS/Billing", "EstimatedCharges", "Currency", "USD", { label = "this month" }]]
        }
      },
      {
        type = "metric", x = 8, y = 15, width = 16, height = 6
        properties = {
          title   = "Requests per table (write units per 5 min)", region = var.region, view = "bar", stat = "Sum", period = 300
          metrics = [for t in local.tables : ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", t, { label = t }]]
        }
      }
    ]
  })
}

output "cloudwatch_dashboard_url" {
  value = "${local.console}/cloudwatch/home?region=${var.region}#dashboards/dashboard/${var.prefix}"
}
