import vk_api

# Пример работы с API
vk_session = vk_api.VkApi(
    token='vk1.a.C7QVpbsFQBaquf7__OTT4LSLyf_xe9-2aYASKkgQRusmvfASxe8b9EQAnoL4XHI8oCNDE-gh5l64-FIp-Nz1V13MX6TOEG3V3gW-C79ft4mKnnbVLge2aqM6-c_1ZLaM_0Ue8qpew1jnZcafUyoKZObMYLvhuPeBt2Cq5a5vbKZSqfdqFlaZHNIPJepnhYgG')
vk = vk_session.get_api()

# Пример получения списка друзей
friends = vk.friends.get(fields='bdate')
for friend in friends['items']:
    if 'bdate' in friend:
        print(friend['first_name'], friend['last_name'], friend['bdate'])
