data "aws_caller_identity" "me" {}

locals {
  account    = data.aws_caller_identity.me.account_id
  ssm_arn    = "arn:aws:ssm:${var.region}:${local.account}:parameter${var.ssm_prefix}"
  table_arns = [for t in [aws_dynamodb_table.agents, aws_dynamodb_table.counters, aws_dynamodb_table.usage, aws_dynamodb_table.incidents] : t.arn]
  table_env = {
    T_AGENTS    = aws_dynamodb_table.agents.name
    T_COUNTERS  = aws_dynamodb_table.counters.name
    T_USAGE     = aws_dynamodb_table.usage.name
    T_INCIDENTS = aws_dynamodb_table.incidents.name
    SSM_PREFIX  = var.ssm_prefix
  }
  # Names (not resource references) so gateway <-> worker wiring has no cycles.
  fn_arn = { for k in ["gateway", "demo", "bot"] :
  k => "arn:aws:lambda:${var.region}:${local.account}:function:${var.prefix}-${k}" }
}

# One zip of src/ shared by every Lambda (stdlib + boto3 only, no packaging step).
data "archive_file" "src" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/build/src.zip"
  excludes    = ["__pycache__"]
}

# Global kill switch. Terraform creates it "off" and then never touches the value.
resource "aws_ssm_parameter" "kill_all" {
  name  = "${var.ssm_prefix}/kill_all"
  type  = "String"
  tier  = "Standard"
  value = "off"
  lifecycle {
    ignore_changes = [value]
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------------- gateway ----------------

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/aws/lambda/${var.prefix}-gateway"
  retention_in_days = 7
}

resource "aws_iam_role" "gateway" {
  name               = "${var.prefix}-gateway"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "gateway" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.gateway.arn}:*"]
  }
  statement {
    sid       = "Tables"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:BatchGetItem"]
    resources = local.table_arns
  }
  statement {
    sid     = "ReadSecrets"
    actions = ["ssm:GetParameter"]
    resources = [for p in ["kill_all", "admin_key_hash", "groq_api_key", "gemini_api_key"] :
    "${local.ssm_arn}/${p}"]
  }
  statement {
    sid       = "KillSwitch"
    actions   = ["ssm:PutParameter"]
    resources = [aws_ssm_parameter.kill_all.arn]
  }
  statement {
    sid       = "AsyncWorkers"
    actions   = ["lambda:InvokeFunction"]
    resources = [local.fn_arn.demo, local.fn_arn.bot]
  }
  statement {
    sid       = "DecryptViaSsmOnly"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "gateway" {
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway.json
}

resource "aws_lambda_function" "gateway" {
  function_name    = "${var.prefix}-gateway"
  role             = aws_iam_role.gateway.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "gateway_handler.handler"
  filename         = data.archive_file.src.output_path
  source_code_hash = data.archive_file.src.output_base64sha256
  memory_size      = 256
  timeout          = 30 # 2 providers x 10 s timeout + overhead

  environment {
    variables = merge(local.table_env, {
      ALLOWED_ORIGIN = var.allowed_origin
      BOT_FUNCTION   = "${var.prefix}-bot"
      DEMO_FUNCTION  = "${var.prefix}-demo"
    })
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.gateway.name
  }
  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_lambda_function_url" "gateway" {
  function_name      = aws_lambda_function.gateway.function_name
  authorization_type = "NONE" # app-level API keys; CORS handled in code for public routes only
}

resource "aws_lambda_permission" "gateway_url" {
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.gateway.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# Since late 2025 a public Function URL also needs lambda:InvokeFunction,
# limited here to calls that arrive through the Function URL.
resource "aws_lambda_permission" "gateway_url_invoke" {
  statement_id             = "PublicFunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.gateway.function_name
  principal                = "*"
  invoked_via_function_url = true
}
