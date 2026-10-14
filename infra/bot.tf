# Telegram ops-console bot (+ alerts, daily report).

# ---------------- Telegram bot ----------------

resource "aws_cloudwatch_log_group" "bot" {
  name              = "/aws/lambda/${var.prefix}-bot"
  retention_in_days = 7
}

resource "aws_iam_role" "bot" {
  name               = "${var.prefix}-bot"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "bot" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bot.arn}:*"]
  }
  statement {
    sid       = "ReadOnlyTables"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"]
    resources = local.table_arns
  }
  statement {
    actions = ["ssm:GetParameter"]
    resources = [for p in ["telegram_bot_token", "telegram_chat_id", "telegram_webhook_secret", "kill_all"] :
    "${local.ssm_arn}/${p}"]
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
  statement {
    sid       = "AdminActionsViaGateway"
    actions   = ["lambda:InvokeFunction"]
    resources = [local.fn_arn.gateway]
  }
}

resource "aws_iam_role_policy" "bot" {
  role   = aws_iam_role.bot.id
  policy = data.aws_iam_policy_document.bot.json
}

resource "aws_lambda_function" "bot" {
  function_name    = "${var.prefix}-bot"
  role             = aws_iam_role.bot.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "bot_handler.handler"
  filename         = data.archive_file.src.output_path
  source_code_hash = data.archive_file.src.output_base64sha256
  memory_size      = 128
  timeout          = 20

  environment {
    variables = merge(local.table_env, {
      GATEWAY_FUNCTION = "${var.prefix}-gateway"
    })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.bot.name
  }
  depends_on = [aws_iam_role_policy.bot]
}

resource "aws_lambda_function_event_invoke_config" "bot" {
  function_name          = aws_lambda_function.bot.function_name
  maximum_retry_attempts = 0
}

# Telegram webhook endpoint (secret-token header checked in code).
resource "aws_lambda_function_url" "bot" {
  function_name      = aws_lambda_function.bot.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "bot_url" {
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.bot.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "bot_url_invoke" {
  statement_id             = "PublicFunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.bot.function_name
  principal                = "*"
  invoked_via_function_url = true
}


output "bot_webhook_url" {
  value = aws_lambda_function_url.bot.function_url
}
