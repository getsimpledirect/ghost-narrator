import json

with open("n8n/workflows/ghost-audio-pipeline.json", "r") as f:
    workflow = json.load(f)

# New HMAC validation node
hmac_node = {
    "id": "hmac-validate",
    "name": "Validate HMAC Signature",
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [250, 300],
    "parameters": {
        "jsCode": """// Validate Ghost webhook HMAC-SHA256 signature
const crypto = require('crypto');
const secret = $env.N8N_GHOST_WEBHOOK_SECRET;

if (!secret) {
  console.warn('N8N_GHOST_WEBHOOK_SECRET not set — webhook is unauthenticated');
  return [{$json: $json}];
}

const signature = $request.headers['x-ghost-signature'];
if (!signature) {
  throw new Error('Missing X-Ghost-Signature header — request rejected');
}

// Ghost signature format: "sha256=<hex>, t=<timestamp>"
const sigMatch = signature.match(/sha256=([a-f0-9]+)/);
if (!sigMatch) {
  throw new Error('Invalid X-Ghost-Signature format');
}

const body = JSON.stringify($json);
const expected = crypto.createHmac('sha256', secret).update(body).digest('hex');

if (!crypto.timingSafeEqual(Buffer.from(sigMatch[1], 'hex'), Buffer.from(expected, 'hex'))) {
  throw new Error('X-Ghost-Signature validation failed — request rejected');
}

return [{$json: $json}];"""
    },
}

# Insert new node after the webhook
new_nodes = []
for node in workflow["nodes"]:
    new_nodes.append(node)
    if node["id"] == "webhook-ghost":
        new_nodes.append(hmac_node)

workflow["nodes"] = new_nodes

# Update connections - webhook now connects to HMAC node
workflow["connections"]["Ghost: Post Published"]["main"][0][0]["node"] = (
    "Validate HMAC Signature"
)

# Add connection from HMAC node to Extract Post Metadata
workflow["connections"]["Validate HMAC Signature"] = {
    "main": [[{"node": "Extract Post Metadata", "type": "main", "index": 0}]]
}

# Update positions for remaining nodes to shift right
for node in workflow["nodes"]:
    if node["id"] not in ["webhook-ghost", "hmac-validate"]:
        node["position"][0] += 250

with open("n8n/workflows/ghost-audio-pipeline.json", "w") as f:
    json.dump(workflow, f, indent=2)

print("Added HMAC validation node")
