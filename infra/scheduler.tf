# Background traffic every 15 min and the daily Telegram report.

# ---------------- EventBridge Scheduler ----------------

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = [aws_lambda_function.demo.arn, aws_lambda_function.bot.arn]
    }]
  })
}

resource "aws_scheduler_schedule" "traffic" {
  name                = "${var.prefix}-traffic"
  schedule_expression = "rate(15 minutes)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.demo.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ job = "traffic" })
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}

resource "aws_scheduler_schedule" "daily_report" {
  name                         = "${var.prefix}-daily-report"
  schedule_expression          = "cron(0 9 * * ? *)"
  schedule_expression_timezone = "America/New_York"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.bot.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ type = "daily_report" })
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
