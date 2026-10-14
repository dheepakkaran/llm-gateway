# Demo runner (+ background traffic): calls the gateway over HTTPS like a real agent.

# ---------------- demo runner ----------------

resource "aws_cloudwatch_log_group" "demo" {
  name              = "/aws/lambda/${var.prefix}-demo"
  retention_in_days = 7
}

resource "aws_iam_role" "demo" {
  name               = "${var.prefix}-demo"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "demo" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.demo.arn}:*"]
  }
  statement {
    sid       = "DemoAgentsAndState"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.agents.arn, aws_dynamodb_table.counters.arn]
  }
  statement {
    actions   = ["ssm:GetParameter"]
    resources = ["${local.ssm_arn}/demo_key_secret"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "demo" {
  role   = aws_iam_role.demo.id
  policy = data.aws_iam_policy_document.demo.json
}

resource "aws_lambda_function" "demo" {
  function_name    = "${var.prefix}-demo"
  role             = aws_iam_role.demo.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "demo_handler.handler"
  filename         = data.archive_file.src.output_path
  source_code_hash = data.archive_file.src.output_base64sha256
  memory_size      = 256
  timeout          = 300

  environment {
    variables = merge(local.table_env, {
      GATEWAY_URL = aws_lambda_function_url.gateway.function_url
    })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.demo.name
  }
  depends_on = [aws_iam_role_policy.demo]
}

# Async invokes only (from the gateway / scheduler): no retries, so a failed demo
# never re-runs and burns requests twice.
resource "aws_lambda_function_event_invoke_config" "demo" {
  function_name          = aws_lambda_function.demo.function_name
  maximum_retry_attempts = 0
}
