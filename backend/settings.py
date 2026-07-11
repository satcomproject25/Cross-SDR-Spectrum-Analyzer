import json


class Settings:

    def __init__(self):

        with open("config/settings.json") as f:

            self.data = json.load(f)

    def get(self, key):

        return self.data.get(key)