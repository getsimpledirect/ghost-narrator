import json

with open("n8n/workflows/ghost-audio-callback.json", "r") as f:
    workflow = json.load(f)

# Find and fix the Extract API Keys node
for node in workflow["nodes"]:
    if node["id"] == "extract-api-keys":
        node["parameters"][
            "jsCode"
        ] = """// Use siteSlug from the callback payload (set by Check Status & Parse Job ID node)
const slug = $json.siteSlug;
const adminApiKey = slug === 'site1'
  ? $env.GHOST_SITE1_ADMIN_API_KEY
  : slug === 'site2'
  ? $env.GHOST_SITE2_ADMIN_API_KEY
  : null;

if (!adminApiKey) {
  throw new Error(`No admin API key configured for site slug: "${slug}". Expected 'site1' or 'site2'.`);
}

// Get the Ghost URL based on site slug
const ghostUrl = slug === 'site1' 
  ? $env.GHOST_SITE1_URL 
  : slug === 'site2' 
  ? $env.GHOST_SITE2_URL 
  : null;

if (!ghostUrl) {
  throw new Error(`No Ghost URL configured for site slug: "${slug}". Expected GHOST_SITE1_URL or GHOST_SITE2_URL.`);
}

const [keyId, secret] = adminApiKey.split(':');

return [{
  json: {
    ...$json,
    ghostKeyId: keyId,
    ghostSecret: secret,
    ghostUrl: ghostUrl
  }
}];"""
        print("Fixed Extract API Keys node")
        break

with open("n8n/workflows/ghost-audio-callback.json", "w") as f:
    json.dump(workflow, f, indent=2)

print("Done")
