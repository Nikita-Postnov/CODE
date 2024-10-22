import requests

url = "https://api.mindbox.ru/v3/operations/sync?endpointId=hiring.Website&operation=get.user"
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Authorization": 'Mindbox secretKey="QQ5oyl5DLBhKeLrQO1A2"'
}
data = {
    "customer": {
        "email": "demo@mindbox.cloud"
    }
}

response = requests.post(url, headers=headers, json=data)

print(response.json())
