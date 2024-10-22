import requests

url = "https://api.mindbox.ru/v3/operations/sync?endpointld=hiring.Website&operation=get.user"
headers = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Authorization": 'Мindbox secretKey = "QQ5oyl5DLBhKelRQO1A2"'
}
data = {
    "customer": {
        "email": "demo@mindbox.cloud"
    }
}

response = requests.post(url, headers=headers, json=data)

print(response.json())
