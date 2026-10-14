"""Thin AWS wrappers (DynamoDB, SSM, Lambda). All business logic lives in the
pure modules; this file only moves data in and out.

Throttling of any DynamoDB call raises Busy -> the gateway fails CLOSED (429)
and never calls a provider without having counted the request.
"""
import json
import time
import zlib
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

import config

_CFG = Config(retries={"max_attempts": 2, "mode": "standard"},
              connect_timeout=2, read_timeout=4)
_THROTTLE = {"ProvisionedThroughputExceededException", "ThrottlingException",
             "RequestLimitExceeded"}
_res = {}


class Busy(Exception):
    """DynamoDB throttled us: fail closed."""


def _ddb():
    if "ddb" not in _res:
        _res["ddb"] = boto3.resource("dynamodb", region_name=config.REGION, config=_CFG)
    return _res["ddb"]


def _client(name):
    if name not in _res:
        _res[name] = boto3.client(name, region_name=config.REGION, config=_CFG)
    return _res[name]


def table(name):
    return _ddb().Table(name)


def plain(x):
    """DynamoDB Decimals/sets -> plain JSON-friendly Python."""
    if isinstance(x, list):
        return [plain(i) for i in x]
    if isinstance(x, set):
        return sorted(plain(i) for i in x)
    if isinstance(x, dict):
        return {k: plain(v) for k, v in x.items()}
    if isinstance(x, Decimal):
        return int(x) if x == x.to_integral_value() else float(x)
    return x


def _guard(fn):
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except ClientError as e:
            if e.response["Error"]["Code"] in _THROTTLE:
                raise Busy() from e
            raise
    return wrap


def _cond_failed(e):
    return e.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ---------------- agents ----------------

@_guard
def get_agent(agent_id, consistent=False):
    r = table(config.T_AGENTS).get_item(Key={"agent_id": agent_id}, ConsistentRead=consistent)
    return plain(r.get("Item")) if "Item" in r else None


@_guard
def put_agent(item, overwrite=False):
    kw = {} if overwrite else {"ConditionExpression": "attribute_not_exists(agent_id)"}
    try:
        table(config.T_AGENTS).put_item(Item=item, **kw)
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


@_guard
def set_agent_status(agent_id, new_status, now, cooldown_until=0, last_suspended_at=None,
                     expect=None, expect_cooldown=None, extra=None):
    """Conditional status change. Returns False if the expected state didn't hold."""
    names = {"#s": "status"}
    vals = {":s": new_status, ":c": int(cooldown_until), ":t": int(now)}
    expr = "SET #s = :s, cooldown_until = :c, status_changed_at = :t"
    if last_suspended_at is not None:
        expr += ", last_suspended_at = :l"
        vals[":l"] = int(last_suspended_at)
    for k, v in (extra or {}).items():
        expr += f", {k} = :x_{k}"
        vals[f":x_{k}"] = v
    cond = "attribute_exists(agent_id)"
    if expect:
        cond += " AND (#s IN (" + ",".join(f":e{i}" for i in range(len(expect))) + ")"
        if "ACTIVE" in expect:
            cond += " OR attribute_not_exists(#s)"
        cond += ")"
        vals.update({f":e{i}": s for i, s in enumerate(expect)})
    if expect_cooldown is not None:
        cond += " AND cooldown_until = :ec"
        vals[":ec"] = int(expect_cooldown)
    try:
        table(config.T_AGENTS).update_item(
            Key={"agent_id": agent_id}, UpdateExpression=expr, ConditionExpression=cond,
            ExpressionAttributeNames=names, ExpressionAttributeValues=vals)
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


@_guard
def set_agent_limits(agent_id, limits):
    try:
        table(config.T_AGENTS).update_item(
            Key={"agent_id": agent_id}, UpdateExpression="SET limits = :l",
            ConditionExpression="attribute_exists(agent_id)",
            ExpressionAttributeValues={":l": _ddb_safe(limits)})
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


@_guard
def batch_get(table_name, keys):
    """keys: list of key dicts. Returns list of plain items (any order)."""
    out = []
    for i in range(0, len(keys), 100):
        req = {table_name: {"Keys": keys[i:i + 100]}}
        for _ in range(5):
            r = _ddb().batch_get_item(RequestItems=req)
            out += [plain(x) for x in r["Responses"].get(table_name, [])]
            req = r.get("UnprocessedKeys") or {}
            if not req:
                break
            time.sleep(0.2)
    return out


# ---------------- counters table: registry, windows, snapshots ----------------

def wkey(agent_id):
    return {"pk": "w#" + agent_id}


@_guard
def registry_add(agent_id):
    table(config.T_COUNTERS).update_item(
        Key={"pk": "registry"}, UpdateExpression="ADD ids :i",
        ExpressionAttributeValues={":i": {agent_id}})


@_guard
def registry_ids():
    r = table(config.T_COUNTERS).get_item(Key={"pk": "registry"})
    return sorted(r.get("Item", {}).get("ids", set()))


@_guard
def get_window(agent_id):
    """Strongly consistent read: (encoded window string or '', version)."""
    r = table(config.T_COUNTERS).get_item(Key=wkey(agent_id), ConsistentRead=True)
    item = r.get("Item") or {}
    return item.get("w", ""), int(item.get("ver", 0))


@_guard
def put_window(agent_id, encoded, ver):
    """Optimistic-locked write. False if someone else wrote first (retry)."""
    ttl = int(time.time()) + 35 * 86400
    try:
        table(config.T_COUNTERS).update_item(
            Key=wkey(agent_id),
            UpdateExpression="SET w = :w, ver = :nv, #ttl = :ttl",
            ConditionExpression="attribute_not_exists(ver) OR ver = :v",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":w": encoded, ":nv": ver + 1, ":v": ver, ":ttl": ttl})
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


@_guard
def get_blob(pk, consistent=False):
    """Compressed JSON blob items (stats snapshot, demo state). -> (dict|None, ver, built_at)."""
    r = table(config.T_COUNTERS).get_item(Key={"pk": pk}, ConsistentRead=consistent)
    item = r.get("Item")
    if not item:
        return None, 0, 0
    data = json.loads(zlib.decompress(bytes(item["data"].value)))
    return data, int(item.get("ver", 0)), int(item.get("built_at", 0))


@_guard
def put_blob(pk, data, ver, built_at, cond_built_before=None):
    """Write a blob if ver matches (or, for snapshots, if the old one is stale)."""
    vals = {":d": zlib.compress(json.dumps(data, separators=(",", ":")).encode(), 6),
            ":nv": ver + 1, ":b": int(built_at), ":v": ver}
    cond = "attribute_not_exists(ver) OR ver = :v"
    if cond_built_before is not None:
        cond = "attribute_not_exists(built_at) OR built_at < :bb"
        vals[":bb"] = int(cond_built_before)
        del vals[":v"]
    try:
        table(config.T_COUNTERS).update_item(
            Key={"pk": pk}, UpdateExpression="SET #d = :d, ver = :nv, built_at = :b",
            ConditionExpression=cond, ExpressionAttributeNames={"#d": "data"},
            ExpressionAttributeValues=vals)
        return True
    except ClientError as e:
        if _cond_failed(e):
            return False
        raise


# ---------------- usage + incidents ----------------

def sort_key(now, rid):
    return f"{int(now * 1000):014d}#{rid}"


@_guard
def put_usage(agent_id, now, rid, fields):
    item = {"agent_id": agent_id, "sk": sort_key(now, rid), "ttl": int(now) + 30 * 86400}
    item.update(_ddb_safe(fields))
    table(config.T_USAGE).put_item(Item=item)


@_guard
def put_incident(agent_id, now, fields):
    item = {"agent_id": agent_id, "sk": sort_key(now, "i"), "ttl": int(now) + 90 * 86400}
    item.update(_ddb_safe(fields))
    table(config.T_INCIDENTS).put_item(Item=item)


@_guard
def query_recent(table_name, agent_id, limit=20, since=None):
    cond = Key("agent_id").eq(agent_id)
    if since is not None:
        cond = cond & Key("sk").gte(f"{int(since * 1000):014d}")
    kw = {"KeyConditionExpression": cond, "ScanIndexForward": False}
    if limit:
        kw["Limit"] = limit
    items, last = [], None
    while True:
        if last:
            kw["ExclusiveStartKey"] = last
        r = table(table_name).query(**kw)
        items += [plain(x) for x in r["Items"]]
        last = r.get("LastEvaluatedKey")
        if not last or (limit and len(items) >= limit):
            return items[:limit] if limit else items


def _ddb_safe(d):
    """floats -> Decimal, drop None (DynamoDB rejects both)."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, float):
            v = Decimal(str(round(v, 8)))
        elif isinstance(v, dict):
            v = _ddb_safe(v)
        out[k] = v
    return out


# ---------------- SSM ----------------

_ssm_cache = {}


def param(name, decrypt=True, cache_s=300):
    """Cached SSM read. Missing parameter -> None."""
    hit = _ssm_cache.get(name)
    if hit and time.time() - hit[1] < cache_s:
        return hit[0]
    try:
        v = _client("ssm").get_parameter(Name=config.SSM_PREFIX + "/" + name,
                                         WithDecryption=decrypt)["Parameter"]["Value"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ParameterNotFound":
            raise
        v = None
    _ssm_cache[name] = (v, time.time())
    return v


def set_param(name, value):
    _client("ssm").put_parameter(Name=config.SSM_PREFIX + "/" + name, Value=value,
                                 Type="String", Overwrite=True)
    _ssm_cache[name] = (value, time.time())


# ---------------- Lambda ----------------

def invoke_async(function_name, payload):
    _client("lambda").invoke(FunctionName=function_name, InvocationType="Event",
                             Payload=json.dumps(payload).encode())
