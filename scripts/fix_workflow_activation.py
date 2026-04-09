import json

# Fix Task 8: callback workflow
with open("n8n/workflows/ghost-audio-callback.json", "r") as f:
    workflow = json.load(f)

# Set active to true
workflow["active"] = True
print("Set active=true for callback workflow")

# Fix Task 14: main workflow - activate and add slug error handling
with open("n8n/workflows/ghost-audio-pipeline.json", "r") as f:
    pipeline = json.load(f)

# Set active to true
pipeline["active"] = True
print("Set active=true for main pipeline")

# Find and update the Extract Post Metadata node to throw error on unrecognised site
for node in pipeline["nodes"]:
    if node["id"] == "extract-metadata":
        # The current code has a fallback that silently uses site1
        # We need to add error handling
        old_code = node["parameters"]["jsCode"]
        # The IIFE is: return h.includes(s1h) ? s1 : h.includes(s2h) ? s2 : s1;
        # We need to change it to throw on unrecognised
        new_code = old_code.replace(
            "return h.includes(s1h) ? s1 : h.includes(s2h) ? s2 : s1;",
            """if (h.includes(s1h)) return s1;
if (h.includes(s2h)) return s2;
throw new Error(`Unrecognised site hostname: "${h}". Configure GHOST_SITE1_URL or GHOST_SITE2_URL to match.`);""",
        )
        node["parameters"]["jsCode"] = new_code
        print("Added unrecognised site hostname error")
        break

with open("n8n/workflows/ghost-audio-pipeline.json", "w") as f:
    json.dump(pipeline, f, indent=2)

with open("n8n/workflows/ghost-audio-callback.json", "w") as f:
    json.dump(workflow, f, indent=2)

print("Done")
