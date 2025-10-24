import json

with open('my_accounts.json', 'r') as f:
    data = json.load(f)
    
accounts = data.get("accounts", [])
print(",".join(accounts))