# All tables PROVISIONED (no autoscaling, no GSIs). Always-free tier allows
# 25 RCU + 25 WCU in total across the region:
#   RCU: agents 3 + counters 13 + usage 5 + incidents 3 = 24
#   WCU: agents 2 + counters 12 + usage 8 + incidents 2 = 24
# Encryption at rest uses the default AWS-owned key (free; no KMS key created).

locals {
  rcu = { agents = 3, counters = 13, usage = 5, incidents = 3 }
  wcu = { agents = 2, counters = 12, usage = 8, incidents = 2 }
}

resource "aws_dynamodb_table" "agents" {
  name           = "${var.prefix}-agents"
  billing_mode   = "PROVISIONED"
  read_capacity  = local.rcu.agents
  write_capacity = local.wcu.agents
  hash_key       = "agent_id"

  attribute {
    name = "agent_id"
    type = "S"
  }
}

# Per-agent window items (w#<agent>), registry, stats snapshot, demo state.
resource "aws_dynamodb_table" "counters" {
  name           = "${var.prefix}-counters"
  billing_mode   = "PROVISIONED"
  read_capacity  = local.rcu.counters
  write_capacity = local.wcu.counters
  hash_key       = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "usage" {
  name           = "${var.prefix}-usage"
  billing_mode   = "PROVISIONED"
  read_capacity  = local.rcu.usage
  write_capacity = local.wcu.usage
  hash_key       = "agent_id"
  range_key      = "sk"

  attribute {
    name = "agent_id"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "incidents" {
  name           = "${var.prefix}-incidents"
  billing_mode   = "PROVISIONED"
  read_capacity  = local.rcu.incidents
  write_capacity = local.wcu.incidents
  hash_key       = "agent_id"
  range_key      = "sk"

  attribute {
    name = "agent_id"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

check "free_tier_capacity" {
  assert {
    condition     = sum(values(local.rcu)) <= 25 && sum(values(local.wcu)) <= 25
    error_message = "DynamoDB provisioned capacity must stay within 25 RCU / 25 WCU."
  }
}
