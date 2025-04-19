import requests
import urllib.parse
import json
from playsound import playsound

# 音素データ生成
text = urllib.parse.quote("これはテスト出力です")
response = requests.post("http://localhost:50121/audio_query?text=" + text + "&speaker=10006")

# responseの中身を表示
# print(json.dumps(response.json(), indent=4))

# 音声合成
resp_wav = requests.post("http://localhost:50121/synthesis?speaker=10006", json=response.json())

# バイナリデータ取り出し
data_binary = resp_wav.content

# wavとして書き込み
path = "test.wav"
wr = open(path, "wb")
wr.write(data_binary)
wr.close()

# 再生
playsound(path)
